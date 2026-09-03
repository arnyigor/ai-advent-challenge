import asyncio
import json
import os
import time

import requests

from tools.llm._transport import (
    LLMCallError,
    LLMCancelledError,
    LLMError,
    LLMFatalError,
    LLMModelUnavailableError,
    LLMRetryableError,
    call_with_retries,
    call_with_retries_async,
    stream_sse,
)


# Fallback chain, newest/strongest first. If a model is temporarily unavailable,
# callers should restart the whole comparable experiment on the next model.
MODEL_CHAIN = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
]
PRIMARY_MODEL = MODEL_CHAIN[0]

BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
STREAM_BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
)
TIMEOUT = 60
MAX_RETRIES_PER_MODEL = 2
RETRY_WAIT_S = 10


class GeminiError(LLMError):
    """Базовый класс ошибок Gemini-вызова. Не ретраить вслепую — смотри подкласс."""


class GeminiFatalError(GeminiError, LLMFatalError):
    """Ошибка, при которой ретраи и перебор моделей бессмысленны
    (битый ключ, невалидный аргумент, нет прав)."""


class GeminiCallError(GeminiError, LLMCallError):
    """Обрабатываемая ошибка вызова: модель недоступна или перегружена."""


class GeminiRetryableError(GeminiCallError, LLMRetryableError):
    """Временная ошибка — повторить на той же модели (429/503/500/сеть)."""


class GeminiCancelledError(GeminiError, LLMCancelledError):
    """Запрос отменён извне (cooperative cancellation)."""


class ModelUnavailableError(GeminiCallError, LLMModelUnavailableError):
    """Модель не существует / нет доступа — перейти к следующей модели без пауз."""


_FATAL_STATUS = {
    "INVALID_ARGUMENT",
    "FAILED_PRECONDITION",
    "UNAUTHENTICATED",
    "PERMISSION_DENIED",
}
_RETRYABLE_STATUS = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL", "UNKNOWN"}
_STATUS_TO_CLASS = {
    "NOT_FOUND": ModelUnavailableError,
    "INVALID_ARGUMENT": GeminiFatalError,
    "FAILED_PRECONDITION": GeminiFatalError,
    "UNAUTHENTICATED": GeminiFatalError,
    "PERMISSION_DENIED": GeminiFatalError,
    "RESOURCE_EXHAUSTED": GeminiRetryableError,
    "UNAVAILABLE": GeminiRetryableError,
    "INTERNAL": GeminiRetryableError,
    "UNKNOWN": GeminiRetryableError,
}


def classify_error(status_code, body_text):
    """Классифицирует ошибку по error.status из тела (важнее HTTP-кода:
    400 с NOT_FOUND — модель недоступна, а не плохой аргумент), фолбэк — на код.
    Непарсящееся 4xx консервативно фатально, 5xx — retryable."""
    status = None
    if body_text:
        try:
            status = json.loads(body_text).get("error", {}).get("status")
        except (ValueError, TypeError):
            status = None
    if status in _STATUS_TO_CLASS:
        return _STATUS_TO_CLASS[status]
    if status_code in (429, 503):
        return GeminiRetryableError
    if 400 <= status_code < 500:
        return GeminiFatalError
    if status_code >= 500:
        return GeminiRetryableError
    return GeminiRetryableError


def has_gemini_api_key():
    """Пустая строка и строка из пробелов считаются отсутствием ключа."""
    return bool((os.environ.get("GEMINI_API_KEY") or "").strip())


def _request_payload(prompt, generation_config=None, system_instruction=None):
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    if generation_config:
        payload["generationConfig"] = generation_config
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    return payload


def _headers():
    if not has_gemini_api_key():
        raise RuntimeError("GEMINI_API_KEY не найден — проверь переменную окружения")
    api_key = os.environ.get("GEMINI_API_KEY")
    return {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }


def _raise_for_gemini_response(code, body_text):
    if code == 401 or code == 403:
        raise GeminiFatalError(
            f"HTTP {code}: доступ запрещён (проверь GEMINI_API_KEY)",
            status_code=code,
        )
    if code != 200:
        error_cls = classify_error(code, body_text[:4000])
        label = {
            GeminiFatalError: "fatal",
            ModelUnavailableError: "model unavailable",
            GeminiRetryableError: "retryable",
        }[error_cls]
        raise error_cls(f"HTTP {code} ({label}): {body_text[:300]}", status_code=code)


def call_gemini(
    model, prompt, generation_config=None, system_instruction=None, timeout=TIMEOUT
):
    headers = _headers()
    payload = _request_payload(prompt, generation_config, system_instruction)

    url = BASE_URL.format(model=model)
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise GeminiRetryableError(f"Ошибка сети: {e}") from None

    _raise_for_gemini_response(resp.status_code, resp.text)
    return resp.json()


def call_gemini_with_retries(
    model,
    prompt,
    generation_config=None,
    system_instruction=None,
    quiet=False,
    retry_logger=None,
    cancel_event=None,
):
    return call_with_retries(
        lambda: call_gemini(model, prompt, generation_config, system_instruction),
        max_retries=MAX_RETRIES_PER_MODEL,
        wait_s=RETRY_WAIT_S,
        quiet=quiet,
        retry_logger=retry_logger,
        cancel_event=cancel_event,
        retryable_exc=GeminiRetryableError,
        cancelled_exc=GeminiCancelledError,
        log_label=f"[{model}] ",
    )


def _parse_stream_chunk(chunk):
    resp = extract_response(chunk)
    usage = extract_usage(chunk)
    return {
        "text": resp["text"],
        "finish_reason": resp["finish_reason"],
        "prompt_tokens": usage["prompt_tokens"],
        "output_tokens": usage["output_tokens"],
    }


def _build_stream_result(text, finish_reason, prompt_tokens, output_tokens):
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}]},
                "finishReason": finish_reason or "NO_CANDIDATES",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
        },
    }


async def _call_gemini_stream_once(
    model,
    prompt,
    generation_config=None,
    system_instruction=None,
    timeout=TIMEOUT,
    on_text=None,
    on_state=None,
    cancel_event=None,
):
    headers = _headers()
    payload = _request_payload(prompt, generation_config, system_instruction)
    url = STREAM_BASE_URL.format(model=model)
    return await stream_sse(
        url,
        payload,
        headers,
        timeout=timeout,
        parse_chunk=_parse_stream_chunk,
        build_result=_build_stream_result,
        raise_for_status=_raise_for_gemini_response,
        retryable_exc=GeminiRetryableError,
        cancelled_exc=GeminiCancelledError,
        on_text=on_text,
        on_state=on_state,
        cancel_event=cancel_event,
    )


async def _call_gemini_stream_with_retries_async(
    model,
    prompt,
    generation_config=None,
    system_instruction=None,
    quiet=False,
    retry_logger=None,
    cancel_event=None,
    on_text=None,
    on_state=None,
    on_retry=None,
):
    return await call_with_retries_async(
        lambda: _call_gemini_stream_once(
            model,
            prompt,
            generation_config=generation_config,
            system_instruction=system_instruction,
            on_text=on_text,
            on_state=on_state,
            cancel_event=cancel_event,
        ),
        max_retries=MAX_RETRIES_PER_MODEL,
        wait_s=RETRY_WAIT_S,
        quiet=quiet,
        retry_logger=retry_logger,
        cancel_event=cancel_event,
        retryable_exc=GeminiRetryableError,
        cancelled_exc=GeminiCancelledError,
        on_retry=on_retry,
        log_label=f"[{model}] ",
    )


def call_gemini_stream_with_retries(
    model,
    prompt,
    generation_config=None,
    system_instruction=None,
    quiet=False,
    retry_logger=None,
    cancel_event=None,
    on_text=None,
    on_state=None,
    on_retry=None,
):
    return asyncio.run(
        _call_gemini_stream_with_retries_async(
            model,
            prompt,
            generation_config=generation_config,
            system_instruction=system_instruction,
            quiet=quiet,
            retry_logger=retry_logger,
            cancel_event=cancel_event,
            on_text=on_text,
            on_state=on_state,
            on_retry=on_retry,
        )
    )


def extract_response(data):
    candidates = data.get("candidates") or []
    if not candidates:
        block_reason = data.get("promptFeedback", {}).get("blockReason")
        text = ""
        finish_reason = (
            f"NO_CANDIDATES (blockReason={block_reason})"
            if block_reason
            else "NO_CANDIDATES"
        )
    else:
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        finish_reason = candidate.get("finishReason")

    usage = extract_usage(data)
    return {
        "text": text,
        "finish_reason": finish_reason,
        "output_tokens": usage["output_tokens"],
    }


def extract_usage(data):
    """Счётчики токенов из usageMetadata (None, если метаданных нет)."""
    usage = data.get("usageMetadata", {})
    return {
        "prompt_tokens": usage.get("promptTokenCount"),
        "output_tokens": usage.get("candidatesTokenCount"),
    }


def calculate_stats(text):
    return {
        "words": len(text.split()),
        "characters": len(text),
    }
