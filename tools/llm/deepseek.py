"""DeepSeek OpenAI-compatible transport for Day 3 experiments."""

from __future__ import annotations

import asyncio
import json
import os
import time

import requests


BASE_URL = "https://api.deepseek.com"
CHAT_URL = BASE_URL + "/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"
TIMEOUT = 60
MAX_RETRIES_PER_MODEL = 2
RETRY_WAIT_S = 10


class DeepSeekError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class DeepSeekFatalError(DeepSeekError):
    """Bad key, bad request, or another error retries cannot fix."""


class DeepSeekRetryableError(DeepSeekError):
    """Temporary provider/network error."""


class DeepSeekCancelledError(DeepSeekError):
    """Request was cancelled by the caller."""


class DeepSeekModelUnavailableError(DeepSeekError):
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
    last_error = None
    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise DeepSeekCancelledError("Запрос отменен")
        try:
            return call_deepseek(model, prompt, generation_config, system_instruction)
        except DeepSeekRetryableError as e:
            last_error = e
            wait = RETRY_WAIT_S * attempt
            if not quiet:
                message = (
                    f"  [deepseek:{model}] HTTP {e.status_code}, жду {wait} сек... "
                    f"(попытка {attempt}/{MAX_RETRIES_PER_MODEL})"
                )
                if retry_logger:
                    retry_logger(message)
                else:
                    print(message)
            if cancel_event is not None:
                if cancel_event.wait(wait):
                    raise DeepSeekCancelledError("Запрос отменен")
            else:
                time.sleep(wait)
    assert last_error is not None
    raise last_error


async def _sleep_or_cancel(wait_s, cancel_event):
    deadline = time.monotonic() + wait_s
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise DeepSeekCancelledError("Запрос отменен")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.1, remaining))


async def _cancel_current_task_on_event(cancel_event, task):
    if cancel_event is None:
        return
    while not cancel_event.is_set():
        await asyncio.sleep(0.1)
    task.cancel()


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
    import httpx  # Ленивый импорт: нужен только для стриминга (Day 3), а не для Day 1/2

    payload = _request_payload(model, prompt, generation_config, system_instruction)
    payload["stream"] = True
    payload["stream_options"] = {"include_usage": True}
    timeout_cfg = httpx.Timeout(timeout, connect=10.0)
    current_task = asyncio.current_task()
    cancel_watcher = asyncio.create_task(
        _cancel_current_task_on_event(cancel_event, current_task)
    )
    text_parts = []
    finish_reason = None
    usage = {}
    saw_first_delta = False

    try:
        if on_state:
            on_state("connecting")
        async with httpx.AsyncClient(timeout=timeout_cfg) as client:
            async with client.stream(
                "POST", CHAT_URL, json=payload, headers=_headers()
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    _raise_for_response(response.status_code, body)

                if on_state:
                    on_state("waiting_first_token")

                async for line in response.aiter_lines():
                    if cancel_event is not None and cancel_event.is_set():
                        raise DeepSeekCancelledError("Запрос отменен")
                    if not line.startswith("data:"):
                        continue
                    raw = line.removeprefix("data:").strip()
                    if not raw:
                        continue
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except ValueError:
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    choice = (chunk.get("choices") or [{}])[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if not delta:
                        continue
                    if not saw_first_delta and on_state:
                        on_state("streaming")
                    saw_first_delta = True
                    text_parts.append(delta)
                    if on_text:
                        on_text(delta)

        if on_state:
            on_state("finalizing")
        result = _compatible_response("".join(text_parts), finish_reason, usage)
        if on_state:
            on_state("complete")
        return result
    except asyncio.CancelledError:
        raise DeepSeekCancelledError("Запрос отменен") from None
    except httpx.HTTPError as e:
        raise DeepSeekRetryableError(f"Ошибка сети DeepSeek: {e}") from None
    finally:
        cancel_watcher.cancel()


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
    last_error = None
    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise DeepSeekCancelledError("Запрос отменен")
        try:
            return await _call_deepseek_stream_once(
                model,
                prompt,
                generation_config=generation_config,
                system_instruction=system_instruction,
                on_text=on_text,
                on_state=on_state,
                cancel_event=cancel_event,
            )
        except DeepSeekRetryableError as e:
            last_error = e
            wait = RETRY_WAIT_S * attempt
            if on_retry:
                on_retry(attempt, wait, str(e))
            if not quiet:
                message = (
                    f"  [deepseek:{model}] HTTP {e.status_code}, жду {wait} сек... "
                    f"(попытка {attempt}/{MAX_RETRIES_PER_MODEL})"
                )
                if retry_logger:
                    retry_logger(message)
                else:
                    print(message)
            await _sleep_or_cancel(wait, cancel_event)
    assert last_error is not None
    raise last_error


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
