import os
import time

import requests


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
TIMEOUT = 60
MAX_RETRIES_PER_MODEL = 2
RETRY_WAIT_S = 10


class GeminiCallError(RuntimeError):
    """Handled Gemini call error: network issue, retryable model error, etc."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def has_gemini_api_key():
    """Пустая строка и строка из пробелов считаются отсутствием ключа."""
    return bool((os.environ.get("GEMINI_API_KEY") or "").strip())


def call_gemini(
    model, prompt, generation_config=None, system_instruction=None, timeout=TIMEOUT
):
    if not has_gemini_api_key():
        raise RuntimeError("GEMINI_API_KEY не найден — проверь переменную окружения")
    api_key = os.environ.get("GEMINI_API_KEY")

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    if generation_config:
        payload["generationConfig"] = generation_config
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    url = BASE_URL.format(model=model)
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise GeminiCallError(f"Ошибка сети: {e}") from None

    code = resp.status_code
    if code == 401 or code == 403:
        raise RuntimeError(f"HTTP {code}: доступ запрещён (проверь GEMINI_API_KEY)")
    if code != 200:
        body = resp.text[:300]
        retryable = code in (429, 503)
        label = "retryable" if retryable else "fatal"
        raise GeminiCallError(f"HTTP {code} ({label}): {body}", status_code=code)

    return resp.json()


def call_gemini_with_retries(
    model,
    prompt,
    generation_config=None,
    system_instruction=None,
    quiet=False,
    retry_logger=None,
):
    last_error = None
    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        try:
            return call_gemini(model, prompt, generation_config, system_instruction)
        except GeminiCallError as e:
            last_error = e
            if e.status_code is not None and e.status_code not in (429, 503):
                raise
            wait = RETRY_WAIT_S * attempt
            if not quiet:
                message = (
                    f"  [{model}] HTTP {e.status_code}, жду {wait} сек... "
                    f"(попытка {attempt}/{MAX_RETRIES_PER_MODEL})"
                )
                if retry_logger:
                    retry_logger(message)
                else:
                    print(message)
            time.sleep(wait)
    assert (
        last_error is not None
    )  # цикл выполняется хотя бы раз (MAX_RETRIES_PER_MODEL >= 1)
    raise last_error


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

    usage = data.get("usageMetadata", {})
    return {
        "text": text,
        "finish_reason": finish_reason,
        "output_tokens": usage.get("candidatesTokenCount"),
    }


def calculate_stats(text):
    return {
        "words": len(text.split()),
        "characters": len(text),
    }
