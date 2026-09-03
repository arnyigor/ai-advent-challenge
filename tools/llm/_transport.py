"""Общий транспортный слой для провайдеров в tools/llm/*.

Здесь живёт то, что было продублировано почти дословно между gemini.py и
deepseek.py: retry-цикл (sync и async), кооперативная отмена во время ожидания
между попытками и SSE-стриминг с колбэками on_text/on_state.

Провайдер-специфичным остаётся: сборка payload/headers, разбор ответа/чанка
(parse_chunk), классификация HTTP-ошибок (raise_for_status) и форма итогового
ответа (build_result). Модули gemini.py/deepseek.py передают их сюда как
аргументы, а не переопределяют цикл заново.

Иерархия ошибок — базовые классы; каждый провайдер определяет свои подклассы
(GeminiFatalError, DeepSeekFatalError, ...), чтобы существующий код мог ловить
конкретный тип провайдера, а общий код здесь — только по базовому.
"""

import asyncio
import json
import time


class LLMError(RuntimeError):
    """Базовый класс ошибок вызова LLM-провайдера."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class LLMFatalError(LLMError):
    """Ретраи и перебор моделей бессмысленны (битый ключ, невалидный аргумент)."""


class LLMCallError(LLMError):
    """Обрабатываемая ошибка вызова: модель недоступна или перегружена."""


class LLMRetryableError(LLMCallError):
    """Временная ошибка — повторить на той же модели."""


class LLMModelUnavailableError(LLMCallError):
    """Модель не существует / нет доступа — перейти к следующей без пауз."""


class LLMCancelledError(LLMError):
    """Запрос отменён извне (cooperative cancellation)."""


def call_with_retries(
    call_fn,
    *,
    max_retries,
    wait_s,
    quiet,
    retry_logger,
    cancel_event,
    retryable_exc,
    cancelled_exc,
    log_label="",
):
    """Общий синхронный retry-цикл с линейно нарастающей паузой (wait_s * attempt)."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise cancelled_exc("Запрос отменён")
        try:
            return call_fn()
        except retryable_exc as e:
            last_error = e
            wait = wait_s * attempt
            if not quiet:
                message = (
                    f"  {log_label}HTTP {e.status_code}, жду {wait} сек... "
                    f"(попытка {attempt}/{max_retries})"
                )
                if retry_logger:
                    retry_logger(message)
                else:
                    print(message)
            if cancel_event is not None:
                if cancel_event.wait(wait):
                    raise cancelled_exc("Запрос отменён") from None
            else:
                time.sleep(wait)
    assert last_error is not None  # цикл выполняется хотя бы раз (max_retries >= 1)
    raise last_error


async def sleep_or_cancel(wait_s, cancel_event, cancelled_exc):
    deadline = time.monotonic() + wait_s
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise cancelled_exc("Запрос отменён")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.1, remaining))


async def cancel_current_task_on_event(cancel_event, task):
    if cancel_event is None:
        return
    while not cancel_event.is_set():
        await asyncio.sleep(0.1)
    task.cancel()


async def call_with_retries_async(
    call_once,
    *,
    max_retries,
    wait_s,
    quiet,
    retry_logger,
    cancel_event,
    retryable_exc,
    cancelled_exc,
    on_retry=None,
    log_label="",
):
    """Асинхронный аналог call_with_retries для стриминговых вызовов."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise cancelled_exc("Запрос отменён")
        try:
            return await call_once()
        except retryable_exc as e:
            last_error = e
            wait = wait_s * attempt
            if on_retry:
                on_retry(attempt, wait, str(e))
            if not quiet:
                message = (
                    f"  {log_label}HTTP {e.status_code}, жду {wait} сек... "
                    f"(попытка {attempt}/{max_retries})"
                )
                if retry_logger:
                    retry_logger(message)
                else:
                    print(message)
            await sleep_or_cancel(wait, cancel_event, cancelled_exc)
    assert last_error is not None
    raise last_error


async def stream_sse(
    url,
    payload,
    headers,
    *,
    timeout,
    parse_chunk,
    build_result,
    raise_for_status,
    retryable_exc,
    cancelled_exc,
    on_text=None,
    on_state=None,
    cancel_event=None,
    method="POST",
):
    """Общий SSE-стриминг (`data: {...}` построчно) с cooperative cancellation.

    parse_chunk(chunk: dict) -> {"text", "finish_reason", "prompt_tokens", "output_tokens"}
        Разбор одного JSON-чанка в провайдеро-независимую форму. Отсутствующие
        значения — None/"" (см. gemini.py и deepseek.py).
    build_result(text, finish_reason, prompt_tokens, output_tokens) -> dict
        Собирает итоговый ответ в форме, ожидаемой extract_response() провайдера.
    raise_for_status(status_code, body_text)
        Поднимает провайдеро-специфичную ошибку для status_code != 200.
    """
    import httpx  # Ленивый импорт: нужен только для стриминга (Day 3), а не для Day 1/2

    timeout_cfg = httpx.Timeout(timeout, connect=10.0)
    current_task = asyncio.current_task()
    cancel_watcher = asyncio.create_task(
        cancel_current_task_on_event(cancel_event, current_task)
    )
    text_parts = []
    finish_reason = None
    prompt_tokens = 0
    output_tokens = 0
    saw_first_chunk = False

    try:
        if on_state:
            on_state("connecting")
        async with httpx.AsyncClient(timeout=timeout_cfg) as client:
            async with client.stream(
                method, url, json=payload, headers=headers
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise_for_status(response.status_code, body)

                if on_state:
                    on_state("waiting_first_token")

                async for line in response.aiter_lines():
                    if cancel_event is not None and cancel_event.is_set():
                        raise cancelled_exc("Запрос отменён")
                    if not line.startswith("data:"):
                        continue
                    raw = line.removeprefix("data:").strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(raw)
                    except ValueError:
                        continue
                    parsed = parse_chunk(chunk)
                    prompt_tokens = parsed.get("prompt_tokens") or prompt_tokens
                    output_tokens = parsed.get("output_tokens") or output_tokens
                    finish_reason = parsed.get("finish_reason") or finish_reason
                    delta = parsed.get("text") or ""
                    if delta:
                        if not saw_first_chunk and on_state:
                            on_state("streaming")
                        saw_first_chunk = True
                        text_parts.append(delta)
                        if on_text:
                            on_text(delta)

        if on_state:
            on_state("finalizing")
        text = "".join(text_parts)
        if on_state:
            on_state("complete")
        return build_result(text, finish_reason, prompt_tokens, output_tokens)
    except asyncio.CancelledError:
        raise cancelled_exc("Запрос отменён") from None
    except httpx.HTTPError as e:
        raise retryable_exc(f"Ошибка сети: {e}") from None
    finally:
        cancel_watcher.cancel()
