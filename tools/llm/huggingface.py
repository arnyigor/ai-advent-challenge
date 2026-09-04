"""Hugging Face Inference Providers transport (OpenAI-compatible router)."""

from __future__ import annotations

import asyncio
import json
import os

import requests

from tools.llm._transport import (
    LLMCancelledError,
    LLMError,
    LLMFatalError,
    LLMModelUnavailableError,
    LLMRetryableError,
    call_with_retries,
    call_with_retries_async,
    stream_sse,
)


BASE_URL = "https://router.huggingface.co/v1"
CHAT_URL = BASE_URL + "/chat/completions"
DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct:nscale"
TIMEOUT = 180
MAX_RETRIES_PER_MODEL = 2
RETRY_WAIT_S = 5


class HuggingFaceError(LLMError):
    pass


class HuggingFaceFatalError(HuggingFaceError, LLMFatalError):
    pass


class HuggingFaceRetryableError(HuggingFaceError, LLMRetryableError):
    pass


class HuggingFaceModelUnavailableError(HuggingFaceError, LLMModelUnavailableError):
    pass


class HuggingFaceCancelledError(HuggingFaceError, LLMCancelledError):
    pass


def _token():
    token = (os.environ.get("HF_TOKEN") or "").strip()
    if token:
        return token
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                token = str(winreg.QueryValueEx(key, "HF_TOKEN")[0]).strip()
                if token:
                    return token
        except (OSError, ValueError):
            pass
    try:
        from huggingface_hub import get_token

        return (get_token() or "").strip()
    except Exception:
        return ""


def has_hf_token():
    return bool(_token())


def _headers():
    token = _token()
    if not token:
        raise RuntimeError("HF_TOKEN не найден — добавь токен Hugging Face в переменные окружения")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _payload(model, prompt, generation_config=None, system_instruction=None, stream=False):
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
    config = generation_config or {}
    payload = {"model": model or DEFAULT_MODEL, "messages": messages, "stream": stream}
    if config.get("temperature") is not None:
        payload["temperature"] = config["temperature"]
    if config.get("maxOutputTokens") is not None:
        payload["max_tokens"] = config["maxOutputTokens"]
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def _raise_for_response(code, body_text):
    if code in (401, 403):
        raise HuggingFaceFatalError(
            f"HTTP {code}: HF_TOKEN не имеет доступа к Inference Providers",
            status_code=code,
        )
    if code in (404, 422):
        raise HuggingFaceModelUnavailableError(
            f"HTTP {code}: модель или провайдер HF недоступны: {body_text[:300]}",
            status_code=code,
        )
    if code in (408, 409, 429) or code >= 500:
        raise HuggingFaceRetryableError(
            f"HTTP {code}: временная ошибка HF Router: {body_text[:300]}",
            status_code=code,
        )
    if code != 200:
        raise HuggingFaceFatalError(
            f"HTTP {code}: ошибка HF Router: {body_text[:300]}",
            status_code=code,
        )


def _compatible_response(text, finish_reason, prompt_tokens, output_tokens):
    return {
        "candidates": [{
            "content": {"parts": [{"text": text or ""}]},
            "finishReason": "MAX_TOKENS" if finish_reason == "length" else (finish_reason or "STOP").upper(),
        }],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
        },
    }


def _extract_response(data):
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = data.get("usage") or {}
    return _compatible_response(
        message.get("content") or "",
        choice.get("finish_reason"),
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )


def call_huggingface(model, prompt, generation_config=None, system_instruction=None):
    try:
        response = requests.post(
            CHAT_URL,
            headers=_headers(),
            json=_payload(model, prompt, generation_config, system_instruction),
            timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise HuggingFaceRetryableError(f"Ошибка сети HF Router: {exc}") from None
    _raise_for_response(response.status_code, response.text)
    return _extract_response(response.json())


def call_huggingface_with_retries(
    model, prompt, generation_config=None, system_instruction=None, quiet=False,
    retry_logger=None, cancel_event=None,
):
    return call_with_retries(
        lambda: call_huggingface(model, prompt, generation_config, system_instruction),
        max_retries=MAX_RETRIES_PER_MODEL,
        wait_s=RETRY_WAIT_S,
        quiet=quiet,
        retry_logger=retry_logger,
        cancel_event=cancel_event,
        retryable_exc=HuggingFaceRetryableError,
        cancelled_exc=HuggingFaceCancelledError,
        log_label=f"[hf:{model}] ",
    )


def _parse_stream_chunk(chunk):
    choice = (chunk.get("choices") or [{}])[0]
    usage = chunk.get("usage") or {}
    return {
        "text": (choice.get("delta") or {}).get("content") or "",
        "finish_reason": choice.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
    }


async def _stream_once(
    model, prompt, generation_config=None, system_instruction=None,
    on_text=None, on_state=None, cancel_event=None,
):
    return await stream_sse(
        CHAT_URL,
        _payload(model, prompt, generation_config, system_instruction, stream=True),
        _headers(),
        timeout=TIMEOUT,
        parse_chunk=_parse_stream_chunk,
        build_result=_compatible_response,
        raise_for_status=_raise_for_response,
        retryable_exc=HuggingFaceRetryableError,
        cancelled_exc=HuggingFaceCancelledError,
        on_text=on_text,
        on_state=on_state,
        cancel_event=cancel_event,
    )


async def _stream_with_retries(
    model, prompt, generation_config=None, system_instruction=None, quiet=False,
    retry_logger=None, cancel_event=None, on_text=None, on_state=None, on_retry=None,
):
    return await call_with_retries_async(
        lambda: _stream_once(
            model, prompt, generation_config, system_instruction,
            on_text, on_state, cancel_event,
        ),
        max_retries=MAX_RETRIES_PER_MODEL,
        wait_s=RETRY_WAIT_S,
        quiet=quiet,
        retry_logger=retry_logger,
        cancel_event=cancel_event,
        retryable_exc=HuggingFaceRetryableError,
        cancelled_exc=HuggingFaceCancelledError,
        on_retry=on_retry,
        log_label=f"[hf:{model}] ",
    )


def call_huggingface_stream_with_retries(
    model, prompt, generation_config=None, system_instruction=None, quiet=False,
    retry_logger=None, cancel_event=None, on_text=None, on_state=None, on_retry=None,
):
    return asyncio.run(_stream_with_retries(
        model, prompt, generation_config, system_instruction, quiet,
        retry_logger, cancel_event, on_text, on_state, on_retry,
    ))


def fetch_model_catalog(timeout=20):
    """Public Router catalog. It contains live provider prices per 1M tokens."""
    response = requests.get(BASE_URL + "/models", timeout=timeout)
    response.raise_for_status()
    return response.json().get("data") or []
