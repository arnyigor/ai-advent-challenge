"""DeepSeek OpenAI-compatible transport for Day 3 experiments."""

from __future__ import annotations

import asyncio
import os

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


BASE_URL = "https://api.deepseek.com"
CHAT_URL = BASE_URL + "/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"
TIMEOUT = 60
MAX_RETRIES_PER_MODEL = 2
RETRY_WAIT_S = 10


class DeepSeekError(LLMError):
    pass


class DeepSeekFatalError(DeepSeekError, LLMFatalError):
    """Bad key, bad request, or another error retries cannot fix."""


class DeepSeekRetryableError(DeepSeekError, LLMRetryableError):
    """Temporary provider/network error."""


class DeepSeekCancelledError(DeepSeekError, LLMCancelledError):
    """Request was cancelled by the caller."""


class DeepSeekModelUnavailableError(DeepSeekError, LLMModelUnavailableError):
    """Selected model is unavailable."""


def has_deepseek_api_key():
    return bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip())


def _headers():
    if not has_deepseek_api_key():
        raise RuntimeError("DEEPSEEK_API_KEY не найден — проверь переменную окружения")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY')}",
    }


def _thinking_payload(generation_config):
    level = ((generation_config or {}).get("thinkingConfig") or {}).get(
        "thinkingLevel", "low"
    )
    if level == "high":
        return {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    return {"thinking": {"type": "disabled"}}


def _request_payload(model, prompt, generation_config=None, system_instruction=None):
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "stream": False,
    }
    if generation_config:
        if generation_config.get("temperature") is not None:
            payload["temperature"] = generation_config["temperature"]
        if generation_config.get("maxOutputTokens") is not None:
            payload["max_tokens"] = generation_config["maxOutputTokens"]
        if generation_config.get("stopSequences"):
            payload["stop"] = generation_config["stopSequences"]
    payload.update(_thinking_payload(generation_config))
    return payload


def _raise_for_response(code, body_text):
    if code in (401, 403):
        raise DeepSeekFatalError(
            f"HTTP {code}: доступ запрещен (проверь DEEPSEEK_API_KEY)",
            status_code=code,
        )
    if code == 404:
        raise DeepSeekModelUnavailableError(
            f"HTTP {code}: модель DeepSeek недоступна: {body_text[:300]}",
            status_code=code,
        )
    if code in (408, 409, 429) or code >= 500:
        raise DeepSeekRetryableError(
            f"HTTP {code}: временная ошибка DeepSeek: {body_text[:300]}",
            status_code=code,
        )
    if code != 200:
        raise DeepSeekFatalError(
            f"HTTP {code}: ошибка DeepSeek: {body_text[:300]}",
            status_code=code,
        )


def _finish_reason(reason):
    if reason == "stop":
        return "STOP"
    if reason == "length":
        return "MAX_TOKENS"
    if reason in ("content_filter", "insufficient_system_resource"):
        return f"NO_CANDIDATES (blockReason={reason})"
    return reason


def _compatible_response(text, finish_reason, usage):
    usage = usage or {}
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text or ""}]},
                "finishReason": _finish_reason(finish_reason),
            }
        ],
        "usageMetadata": {
            "promptTokenCount": usage.get("prompt_tokens"),
            "candidatesTokenCount": usage.get("completion_tokens"),
        },
    }


def _extract_chat_response(data):
    choices = data.get("choices") or []
    if not choices:
        return _compatible_response("", "NO_CANDIDATES", data.get("usage"))
    choice = choices[0]
    message = choice.get("message") or {}
    return _compatible_response(
        message.get("content") or "",
        choice.get("finish_reason"),
        data.get("usage"),
    )


def call_deepseek(
    model, prompt, generation_config=None, system_instruction=None, timeout=TIMEOUT
):
    payload = _request_payload(model, prompt, generation_config, system_instruction)
    try:
        resp = requests.post(
            CHAT_URL, json=payload, headers=_headers(), timeout=timeout
        )
    except requests.exceptions.RequestException as e:
        raise DeepSeekRetryableError(f"Ошибка сети DeepSeek: {e}") from None
    _raise_for_response(resp.status_code, resp.text)
    return _extract_chat_response(resp.json())


def call_deepseek_with_retries(
    model,
    prompt,
    generation_config=None,
    system_instruction=None,
    quiet=False,
    retry_logger=None,
    cancel_event=None,
):
    return call_with_retries(
        lambda: call_deepseek(model, prompt, generation_config, system_instruction),
        max_retries=MAX_RETRIES_PER_MODEL,
        wait_s=RETRY_WAIT_S,
        quiet=quiet,
        retry_logger=retry_logger,
        cancel_event=cancel_event,
        retryable_exc=DeepSeekRetryableError,
        cancelled_exc=DeepSeekCancelledError,
        log_label=f"[deepseek:{model}] ",
    )


def _parse_stream_chunk(chunk):
    usage = chunk.get("usage") or {}
    choice = (chunk.get("choices") or [{}])[0]
    return {
        "text": (choice.get("delta") or {}).get("content") or "",
        "finish_reason": choice.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
    }


def _build_stream_result(text, finish_reason, prompt_tokens, output_tokens):
    return _compatible_response(
        text,
        finish_reason,
        {"prompt_tokens": prompt_tokens, "completion_tokens": output_tokens},
    )


async def _call_deepseek_stream_once(
    model,
    prompt,
    generation_config=None,
    system_instruction=None,
    timeout=TIMEOUT,
    on_text=None,
    on_state=None,
    cancel_event=None,
):
    payload = _request_payload(model, prompt, generation_config, system_instruction)
    payload["stream"] = True
    payload["stream_options"] = {"include_usage": True}
    return await stream_sse(
        CHAT_URL,
        payload,
        _headers(),
        timeout=timeout,
        parse_chunk=_parse_stream_chunk,
        build_result=_build_stream_result,
        raise_for_status=_raise_for_response,
        retryable_exc=DeepSeekRetryableError,
        cancelled_exc=DeepSeekCancelledError,
        on_text=on_text,
        on_state=on_state,
        cancel_event=cancel_event,
    )


async def _call_deepseek_stream_with_retries_async(
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
        lambda: _call_deepseek_stream_once(
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
        retryable_exc=DeepSeekRetryableError,
        cancelled_exc=DeepSeekCancelledError,
        on_retry=on_retry,
        log_label=f"[deepseek:{model}] ",
    )


def call_deepseek_stream_with_retries(
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
        _call_deepseek_stream_with_retries_async(
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
