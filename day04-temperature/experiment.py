"""Day 4 — эксперимент "температура": один промпт, 3 значения temperature,
по N повторов каждое. Между вызовами меняется только temperature.

Preflight нужен потому, что не все провайдеры/модели принимают temperature=1.2
(диапазон Gemini — 0..2, но некоторые модели/провайдеры клампят или фатально
отвергают). Если модель отвергает temperature именно как аргумент —
IncompatibleTemperature, и run_with_model_fallback уходит на следующую модель
в цепочке целиком (см. README раздел "Fallback — только целиком": смешивать
сэмплы разных моделей в одной матрице бессмысленно)."""

from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from tools.llm._transport import LLMCallError, LLMFatalError
from tools.llm.client import Client
from tools.llm.gemini import calculate_stats, extract_response
from tools.llm.pacer import Pacer
from tools.llm.registry import has_key_for, missing_key_message
from tools.llm.runner import run_with_model_fallback

from metrics import compute_verdict, cross_similarity_matrix, summarize

PROMPT = (
    "Объясни начинающему разработчику, что такое Git rebase и чем он "
    "отличается от merge. Обязательно укажи, что происходит с историей "
    "коммитов, назови один риск rebase и объясни, когда его стоит "
    "использовать. В конце добавь одну короткую бытовую аналогию."
)

TEMPERATURES = (0.0, 0.7, 1.2)
MAX_OUTPUT_TOKENS = 2048
THINKING = {"thinkingLevel": "low"}
PROBE_PROMPT = "Ответь одним словом: ок"


class IncompatibleTemperature(LLMCallError):
    """Модель/провайдер фатально отвергла именно значение temperature."""


def prompt_sha256() -> str:
    return hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()[:8]


def build_generation_config(temperature: float) -> dict:
    """Единственное место, где temperature попадает в запрос. topP/topK/seed/
    stopSequences сюда никогда не добавляются — их отсутствие проверяет
    tests/test_day4_config.py."""
    return {
        "temperature": temperature,
        "maxOutputTokens": MAX_OUTPUT_TOKENS,
        "thinkingConfig": dict(THINKING),
    }


def locked_params(repeats: int, concurrency: int) -> dict:
    return {
        "prompt": PROMPT,
        "prompt_sha256": prompt_sha256(),
        "system_instruction": None,
        "maxOutputTokens": MAX_OUTPUT_TOKENS,
        "thinking": THINKING["thinkingLevel"],
        "topP": None,
        "topK": None,
        "seed": None,
        "repeats": repeats,
        "concurrency": concurrency,
    }


def preflight(client: Client, temperature: float = 1.2) -> None:
    try:
        client.call(PROBE_PROMPT, build_generation_config(temperature))
    except LLMFatalError as e:
        msg = str(e).lower()
        if "temperature" in msg or "invalid_argument" in msg:
            raise IncompatibleTemperature(str(e)) from e
        raise


def _run_one(client: Client, temperature: float, repeat: int) -> dict:
    sample_id = f"t{temperature}-r{repeat}"
    gcfg = build_generation_config(temperature)
    started = time.monotonic()
    data = client.call(PROMPT, gcfg)
    latency_ms = int((time.monotonic() - started) * 1000)

    resp = extract_response(data)
    text = resp["text"]
    stats = calculate_stats(text)
    tail = text.strip()[-200:]

    return {
        "id": sample_id,
        "temperature": temperature,
        "repeat": repeat,
        "text": text,
        "tail": tail,
        "finish_reason": resp["finish_reason"],
        "words": stats["words"],
        "characters": stats["characters"],
        "output_tokens": resp["output_tokens"],
        "latency_ms": latency_ms,
    }


def run_matrix(client: Client, repeats: int, concurrency: int, on_event=None) -> dict:
    preflight(client)
    if on_event:
        on_event("preflight_passed", {"model": client.model_spec})

    jobs = [
        (temperature, repeat)
        for temperature in TEMPERATURES
        for repeat in range(1, repeats + 1)
    ]

    samples = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_run_one, client, temperature, repeat): (temperature, repeat)
            for temperature, repeat in jobs
        }
        for future in futures:
            sample = future.result()
            samples.append(sample)
            if on_event:
                on_event("sample_finished", sample)

    samples.sort(key=lambda s: (s["temperature"], s["repeat"]))
    return {
        "samples": samples,
        "metrics": summarize(samples),
    }


def run_experiment(model_chain, repeats: int, concurrency: int, on_event=None) -> dict:
    def _work(model):
        if not has_key_for(model):
            raise IncompatibleTemperature(missing_key_message(model))
        pacer = Pacer(rpm=20)
        client = Client(model, pacer=pacer, quiet=True)
        return run_matrix(client, repeats, concurrency, on_event), model

    def _on_fallback(model, next_model, e):
        if on_event:
            on_event("model_fallback", {"model": model, "next_model": next_model, "error": str(e)})

    (matrix, model_used), _model, attempts = run_with_model_fallback(
        model_chain,
        _work,
        fallback_exc=(LLMCallError,),
        on_fallback=_on_fallback,
    )

    return {
        "schema": "day4-temperature-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_spec": model_used,
        "model_attempts": attempts,
        "locked": locked_params(repeats, concurrency),
        "temperatures": list(TEMPERATURES),
        "samples": matrix["samples"],
        "metrics": matrix["metrics"],
        "cross": cross_similarity_matrix(matrix["samples"], list(TEMPERATURES)),
        "blind_check": None,
        "verdict": compute_verdict(matrix["metrics"]),
    }
