"""Day 5 experiment: same coding prompt, cloud and local model sizes."""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import psutil
import requests

from evaluation import evaluate_answer
from tools.llm.client import Client
from tools.llm.gemini import extract_response, extract_usage
from tools.llm.huggingface import fetch_model_catalog
from tools.llm.registry import has_key_for


PROMPT = """Реализуй на Python 3.11 функцию:

def reconcile_ranges(
    ranges: list[tuple[int, int]],
    exclusions: list[tuple[int, int]],
) -> list[tuple[int, int]]:

Интервалы полуоткрытые: [start, end). Требования:
1. Проверь каждый интервал в обоих списках: границы должны быть int (bool не считается int), start < end. Иначе ValueError.
2. Не изменяй входные списки.
3. Сначала объедини пересекающиеся и соседние ranges.
4. Аналогично нормализуй exclusions, затем вычти их из ranges. Исключение, которое только касается границы, ничего не удаляет.
5. Верни отсортированные непересекающиеся интервалы-кортежи.
6. Нельзя разворачивать интервалы в отдельные точки. Целевая сложность O((n + m) log(n + m)).

Ответ: один блок Python-кода с функцией и затем не более двух предложений о сложности."""

TEMPERATURE = 0.1
MAX_OUTPUT_TOKENS = 1200
HF_PROVIDER = "nscale"
HF_MODELS = (
    {"id": "weak", "label": "HF · 3B", "repo": "Qwen/Qwen2.5-Coder-3B-Instruct", "parameters_b": 3.0},
    {"id": "medium", "label": "HF · 7B", "repo": "Qwen/Qwen2.5-Coder-7B-Instruct", "parameters_b": 7.0},
    {"id": "strong", "label": "HF · 32B", "repo": "Qwen/Qwen2.5-Coder-32B-Instruct", "parameters_b": 32.0},
)
LOCAL_SMALL = {
    "id": "local-small",
    "label": "LOCAL · Qwen3.5 4B Q4_K_M",
    "repo": "qwen3.5:4b",
    "parameters_b": 4.66,
}
LOCAL_CPU = {
    "id": "local-cpu",
    "label": "LOCAL CPU · Qwen3 1.7B Q4_K_M",
    "parameters_b": 1.72,
}
API_MODELS = (
    {
        "id": "gemini-35",
        "label": "API · Gemini 3.5 Flash",
        "spec": "gemini:gemini-3.5-flash",
        "repo": "gemini-3.5-flash",
        "provider": "gemini",
        "parameters_b": None,
        "price": {"input_usd_per_million": 1.50, "output_usd_per_million": 9.00},
    },
    {
        "id": "gemini-36",
        "label": "API · Gemini 3.6 Flash",
        "spec": "gemini:gemini-3.6-flash",
        "repo": "gemini-3.6-flash",
        "provider": "gemini",
        "parameters_b": None,
        "price": {"input_usd_per_million": 0.75, "output_usd_per_million": 3.75},
    },
    {
        "id": "deepseek",
        "label": "API · DeepSeek V4 Flash",
        "spec": "deepseek:deepseek-v4-flash",
        "repo": "deepseek-v4-flash",
        "provider": "deepseek",
        "parameters_b": None,
    },
)


def prompt_sha256() -> str:
    return hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()[:8]


def generation_config() -> dict:
    return {
        "temperature": TEMPERATURE,
        "maxOutputTokens": MAX_OUTPUT_TOKENS,
        "thinkingConfig": {"thinkingLevel": "minimal"},
    }


def _price_snapshot() -> dict:
    result = {}
    try:
        catalog = fetch_model_catalog()
    except Exception:
        catalog = []
    by_id = {item.get("id"): item for item in catalog}
    for model in HF_MODELS:
        providers = by_id.get(model["repo"], {}).get("providers") or []
        provider = next((p for p in providers if p.get("provider") == HF_PROVIDER), None)
        if provider and provider.get("pricing"):
            result[model["id"]] = {
                "provider": HF_PROVIDER,
                "input_usd_per_million": provider["pricing"].get("input"),
                "output_usd_per_million": provider["pricing"].get("output"),
                "catalog_ttft_ms": provider.get("first_token_latency_ms"),
                "catalog_tokens_per_second": provider.get("throughput"),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
    captured_at = datetime.now(timezone.utc)
    for model in API_MODELS:
        if model["provider"] == "deepseek":
            peak = captured_at.weekday() < 5 and (
                1 <= captured_at.hour < 4 or 6 <= captured_at.hour < 10
            )
            multiplier = 1.0 if peak else 0.5
            result[model["id"]] = {
                "provider": "deepseek",
                "tier": "peak" if peak else "off-peak",
                "input_cache_hit_usd_per_million": 0.014 * multiplier,
                "input_usd_per_million": 0.44 * multiplier,
                "output_usd_per_million": 1.32 * multiplier,
                "captured_at": captured_at.isoformat(),
            }
        else:
            result[model["id"]] = {
                "provider": model["provider"],
                **model["price"],
                "tier": "standard paid (free tier may charge $0)",
                "captured_at": captured_at.isoformat(),
            }
    return result


def _cost_usd(prompt_tokens, output_tokens, price):
    if not price or prompt_tokens is None or output_tokens is None:
        return None
    return (
        prompt_tokens * price["input_usd_per_million"]
        + output_tokens * price["output_usd_per_million"]
    ) / 1_000_000


class GpuMonitor:
    def __init__(self):
        self.stop_event = threading.Event()
        self.samples = []
        self.thread = None

    def _sample(self):
        command = [
            "nvidia-smi",
            "--query-gpu=memory.used,utilization.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
        while not self.stop_event.is_set():
            try:
                raw = subprocess.check_output(command, text=True, timeout=2).strip().splitlines()[0]
                memory, utilization, power = [float(part.strip()) for part in raw.split(",")]
                self.samples.append({"vram_mb": memory, "gpu_util_percent": utilization, "power_w": power})
            except Exception:
                pass
            self.stop_event.wait(0.2)

    def __enter__(self):
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def summary(self):
        if not self.samples:
            return None
        return {
            "vram_mb_peak": max(s["vram_mb"] for s in self.samples),
            "gpu_util_percent_peak": max(s["gpu_util_percent"] for s in self.samples),
            "power_w_peak": max(s["power_w"] for s in self.samples),
        }


class CpuProcessMonitor:
    def __init__(self, base_url):
        self.stop_event = threading.Event()
        self.samples = []
        self.thread = None
        self.port = urlparse(base_url).port
        self.process = None

    def _resolve_process(self):
        for connection in psutil.net_connections(kind="tcp"):
            if connection.pid and connection.laddr and connection.laddr.port == self.port:
                return psutil.Process(connection.pid)
        return None

    def _sample(self):
        logical_cpus = psutil.cpu_count() or 1
        try:
            self.process = self._resolve_process()
            if self.process:
                self.process.cpu_percent(None)
        except (psutil.Error, OSError):
            self.process = None
        while not self.stop_event.is_set():
            if self.process:
                try:
                    self.samples.append({
                        "rss_mb": self.process.memory_info().rss / 1024 / 1024,
                        "cpu_percent": self.process.cpu_percent(None) / logical_cpus,
                    })
                except (psutil.Error, OSError):
                    self.process = None
            self.stop_event.wait(0.2)

    def __enter__(self):
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def summary(self):
        if not self.samples:
            return None
        return {
            "ram_mb_peak": max(s["rss_mb"] for s in self.samples),
            "cpu_percent_peak": max(s["cpu_percent"] for s in self.samples),
        }


def _run_hf_sample(model, repeat, price, on_event=None):
    spec = f"hf:{model['repo']}:{HF_PROVIDER}"
    client = Client(spec, quiet=True, stream=True)
    started = time.monotonic()
    first_token_at = None

    def on_text(delta):
        nonlocal first_token_at
        if first_token_at is None:
            first_token_at = time.monotonic()
        if on_event:
            on_event("token_delta", {"model_id": model["id"], "repeat": repeat, "text": delta})

    data = client.call_stream(PROMPT, generation_config(), on_text=on_text)
    finished = time.monotonic()
    response = extract_response(data)
    usage = extract_usage(data)
    output_tokens = usage["output_tokens"]
    elapsed = finished - started
    return {
        "model_id": model["id"],
        "repeat": repeat,
        "backend": "huggingface",
        "model": model["repo"],
        "provider": HF_PROVIDER,
        "text": response["text"],
        "finish_reason": response["finish_reason"],
        "latency_ms": round(elapsed * 1000),
        "ttft_ms": round(((first_token_at or finished) - started) * 1000),
        "prompt_tokens": usage["prompt_tokens"],
        "output_tokens": output_tokens,
        "tokens_per_second": (output_tokens / elapsed) if output_tokens else None,
        "cost_usd": _cost_usd(usage["prompt_tokens"], output_tokens, price),
        "evaluation": evaluate_answer(response["text"]),
        "gpu": None,
    }


def _api_cost(model, usage, metadata, price):
    if model["provider"] != "deepseek":
        return _cost_usd(usage["prompt_tokens"], usage["output_tokens"], price), None, None
    hit_tokens = metadata.get("promptCacheHitTokenCount") or 0
    miss_tokens = metadata.get("promptCacheMissTokenCount")
    if miss_tokens is None:
        miss_tokens = max((usage["prompt_tokens"] or 0) - hit_tokens, 0)
    cost = (
        hit_tokens * price["input_cache_hit_usd_per_million"]
        + miss_tokens * price["input_usd_per_million"]
        + (usage["output_tokens"] or 0) * price["output_usd_per_million"]
    ) / 1_000_000
    return cost, hit_tokens, miss_tokens


def _run_api_sample(model, repeat, price, on_event=None, cancel_event=None):
    # Sync keeps provider-specific usage fields (Gemini thoughts, DeepSeek cache)
    # needed for an honest billable-token cost calculation.
    streaming = False
    client = Client(
        model["spec"], quiet=True, stream=streaming, cancel_event=cancel_event
    )
    started = time.monotonic()
    first_token_at = None

    def on_text(delta):
        nonlocal first_token_at
        if first_token_at is None:
            first_token_at = time.monotonic()
        if on_event:
            on_event("token_delta", {"model_id": model["id"], "repeat": repeat, "text": delta})

    if streaming:
        data = client.call_stream(PROMPT, generation_config(), on_text=on_text)
    else:
        data = client.call(PROMPT, generation_config())
    finished = time.monotonic()
    response = extract_response(data)
    if not streaming and response["text"] and on_event:
        on_event(
            "token_delta",
            {"model_id": model["id"], "repeat": repeat, "text": response["text"]},
        )
    usage = extract_usage(data)
    metadata = data.get("usageMetadata") or {}
    visible_output_tokens = usage["output_tokens"]
    thought_tokens = metadata.get("thoughtsTokenCount") or 0
    output_tokens = (visible_output_tokens or 0) + thought_tokens
    billed_usage = {**usage, "output_tokens": output_tokens}
    cost, cache_hit_tokens, cache_miss_tokens = _api_cost(
        model, billed_usage, metadata, price
    )
    elapsed = finished - started
    return {
        "model_id": model["id"],
        "repeat": repeat,
        "backend": "api",
        "model": model["repo"],
        "provider": model["provider"],
        "text": response["text"],
        "finish_reason": response["finish_reason"],
        "latency_ms": round(elapsed * 1000),
        "ttft_ms": round((first_token_at - started) * 1000) if first_token_at else None,
        "prompt_tokens": usage["prompt_tokens"],
        "output_tokens": output_tokens,
        "visible_output_tokens": visible_output_tokens,
        "thought_tokens": thought_tokens,
        "tokens_per_second": (output_tokens / elapsed) if output_tokens else None,
        "cost_usd": cost,
        "cache_hit_tokens": cache_hit_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        "evaluation": evaluate_answer(response["text"]),
        "gpu": None,
        "cpu": None,
    }


def _local_info(base_url):
    response = requests.get(base_url.rstrip("/") + "/v1/models", timeout=10)
    response.raise_for_status()
    data = response.json()
    item = (data.get("data") or data.get("models") or [{}])[0]
    meta = item.get("meta") or {}
    return {
        "alias": item.get("id") or item.get("name"),
        "parameters": meta.get("n_params"),
        "parameters_b": round(meta["n_params"] / 1_000_000_000, 2) if meta.get("n_params") else 27.0,
        "weights_bytes": meta.get("size"),
        "quantization": meta.get("ftype"),
        "context": meta.get("n_ctx"),
    }


def _ollama_info(base_url, model_name):
    response = requests.post(
        base_url.rstrip("/") + "/api/show",
        json={"model": model_name},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    details = data.get("details") or {}
    return {
        "alias": model_name,
        "parameters_b": LOCAL_SMALL["parameters_b"],
        "parameter_size": details.get("parameter_size"),
        "quantization": details.get("quantization_level"),
        "family": details.get("family"),
    }


def _llamacpp_power(base_url, sleeping):
    """Best-effort VRAM handoff between llama.cpp and Ollama."""
    endpoint = "/sleep" if sleeping else "/wake"
    try:
        response = requests.post(base_url.rstrip("/") + endpoint, timeout=90)
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()
        return response.status_code != 404
    except requests.RequestException:
        return False


def _unload_ollama(base_url, model_name):
    try:
        response = requests.post(
            base_url.rstrip("/") + "/api/generate",
            json={"model": model_name, "keep_alive": 0},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException:
        pass


def _run_ollama_sample(base_url, local, repeat, on_event=None, cancel_event=None):
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": local["alias"],
        "messages": [{"role": "user", "content": PROMPT}],
        "think": False,
        "stream": True,
        "keep_alive": "5m",
        "options": {"temperature": TEMPERATURE, "num_predict": MAX_OUTPUT_TOKENS},
    }
    started = time.monotonic()
    first_token_at = None
    parts = []
    final_chunk = {}
    with GpuMonitor() as monitor:
        with requests.post(url, json=payload, stream=True, timeout=180) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=True):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Эксперимент отменён")
                if not raw_line:
                    continue
                chunk = json.loads(raw_line)
                final_chunk = chunk
                delta = (chunk.get("message") or {}).get("content") or ""
                if delta:
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                    parts.append(delta)
                    if on_event:
                        on_event(
                            "token_delta",
                            {"model_id": LOCAL_SMALL["id"], "repeat": repeat, "text": delta},
                        )
    finished = time.monotonic()
    text = "".join(parts)
    output_tokens = final_chunk.get("eval_count")
    elapsed = finished - started
    eval_duration = final_chunk.get("eval_duration") or 0
    measured_tps = output_tokens / (eval_duration / 1_000_000_000) if output_tokens and eval_duration else None
    return {
        "model_id": LOCAL_SMALL["id"],
        "repeat": repeat,
        "backend": "local",
        "model": local["alias"],
        "provider": "ollama",
        "text": text,
        "finish_reason": final_chunk.get("done_reason", "stop").upper(),
        "latency_ms": round(elapsed * 1000),
        "ttft_ms": round(((first_token_at or finished) - started) * 1000),
        "prompt_tokens": final_chunk.get("prompt_eval_count"),
        "output_tokens": output_tokens,
        "tokens_per_second": measured_tps or ((output_tokens / elapsed) if output_tokens else None),
        "cost_usd": 0.0,
        "evaluation": evaluate_answer(text),
        "gpu": monitor.summary(),
        "load_duration_ms": round((final_chunk.get("load_duration") or 0) / 1_000_000),
    }


def _run_local_sample(
    base_url, local, repeat, model_id="local", resource="gpu",
    on_event=None, cancel_event=None,
):
    url = base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": local["alias"],
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    started = time.monotonic()
    first_token_at = None
    parts = []
    usage = {}
    finish_reason = None
    monitor_context = CpuProcessMonitor(base_url) if resource == "cpu" else GpuMonitor()
    with monitor_context as monitor:
        with requests.post(url, json=payload, stream=True, timeout=180) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=True):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Эксперимент отменён")
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                raw = raw_line.removeprefix("data:").strip()
                if raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(raw)
                except ValueError:
                    continue
                usage = chunk.get("usage") or usage
                choice = (chunk.get("choices") or [{}])[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = (choice.get("delta") or {}).get("content") or ""
                if delta:
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                    parts.append(delta)
                    if on_event:
                        on_event("token_delta", {"model_id": model_id, "repeat": repeat, "text": delta})
    finished = time.monotonic()
    text = "".join(parts)
    output_tokens = usage.get("completion_tokens")
    elapsed = finished - started
    return {
        "model_id": model_id,
        "repeat": repeat,
        "backend": "local",
        "model": local["alias"],
        "provider": "llama.cpp",
        "text": text,
        "finish_reason": (finish_reason or "stop").upper(),
        "latency_ms": round(elapsed * 1000),
        "ttft_ms": round(((first_token_at or finished) - started) * 1000),
        "prompt_tokens": usage.get("prompt_tokens"),
        "output_tokens": output_tokens,
        "tokens_per_second": (output_tokens / elapsed) if output_tokens else None,
        "cost_usd": 0.0,
        "evaluation": evaluate_answer(text),
        "gpu": monitor.summary() if resource == "gpu" else None,
        "cpu": monitor.summary() if resource == "cpu" else None,
    }


def _aggregate(samples, models):
    result = {}
    for model in models:
        group = [s for s in samples if s["model_id"] == model["id"]]
        if not group:
            continue
        values = lambda key: [s[key] for s in group if s.get(key) is not None]
        result[model["id"]] = {
            "label": model["label"],
            "parameters_b": model.get("parameters_b"),
            "latency_ms_median": statistics.median(values("latency_ms")),
            "ttft_ms_median": statistics.median(values("ttft_ms")) if values("ttft_ms") else None,
            "tokens_per_second_median": statistics.median(values("tokens_per_second")) if values("tokens_per_second") else None,
            "output_tokens_median": statistics.median(values("output_tokens")) if values("output_tokens") else None,
            "tests_passed_mean": statistics.mean(s["evaluation"]["passed"] for s in group),
            "tests_total": group[0]["evaluation"]["total"],
            "cost_usd_total": sum(s["cost_usd"] or 0 for s in group),
            "vram_mb_peak": max((s["gpu"] or {}).get("vram_mb_peak", 0) for s in group) or None,
            "ram_mb_peak": max((s.get("cpu") or {}).get("ram_mb_peak", 0) for s in group) or None,
            "cpu_percent_peak": max((s.get("cpu") or {}).get("cpu_percent_peak", 0) for s in group) or None,
        }
    return result


def _verdict(metrics):
    if not metrics:
        return "Нет данных для сравнения."
    if len(metrics) == 1:
        only = next(iter(metrics.values()))
        return (
            f"Проверен только {only['label']}: {only['tests_passed_mean']:.1f}/"
            f"{only['tests_total']} тестов. Для сравнительного вывода нужны остальные модели."
        )
    best_quality = max(item["tests_passed_mean"] for item in metrics.values())
    quality_leaders = [
        key for key, item in metrics.items()
        if item["tests_passed_mean"] == best_quality
    ]
    speed_candidates = {k: v for k, v in metrics.items() if v.get("tokens_per_second_median")}
    fastest = max(speed_candidates, key=lambda key: speed_candidates[key]["tokens_per_second_median"])
    quality_values = [item["tests_passed_mean"] for item in metrics.values()]
    if max(quality_values) - min(quality_values) <= 0.5:
        return (
            "На этой практической задаче модели дали практически одинаковое качество. "
            f"Быстрее всех — {metrics[fastest]['label']}; тяжёлые модели здесь похожи на "
            "микроскоп для забивания гвоздей: умеют больше, но для задачи это не окупается."
        )
    if len(quality_leaders) > 1:
        fastest_leader = min(
            quality_leaders, key=lambda key: metrics[key]["latency_ms_median"]
        )
        leaders = ", ".join(metrics[key]["label"] for key in quality_leaders)
        return (
            f"Максимальное качество ({best_quality:.1f}/10): {leaders}. "
            f"Среди лидеров быстрее отвечает {metrics[fastest_leader]['label']}; "
            "для этой задачи более тяжёлые модели уже похожи на микроскоп для "
            "забивания гвоздей — качество упёрлось в потолок, а время и цена растут."
        )
    quality = quality_leaders[0]
    return (
        f"Лучшее качество тестов: {metrics[quality]['label']}; "
        f"максимальная скорость: {metrics[fastest]['label']}. "
        "Большая модель не гарантирует лучший баланс: сравнивай качество, задержку и цену вместе."
    )


def run_experiment(
    repeats=3, local_url=None, ollama_url=None, local_cpu_url=None,
    include_local=True, include_local_small=True, include_local_cpu=True,
    include_hf=True, include_api=True,
    on_event=None, cancel_event=None,
):
    prices = _price_snapshot()
    samples = []
    model_rows = []
    if include_hf:
        model_rows.extend(dict(model) for model in HF_MODELS)
        for model in HF_MODELS:
            if on_event:
                on_event("model_started", model)
            for repeat in range(1, repeats + 1):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Эксперимент отменён")
                if on_event:
                    on_event("sample_started", {"model_id": model["id"], "repeat": repeat})
                sample = _run_hf_sample(model, repeat, prices.get(model["id"]), on_event)
                samples.append(sample)
                if on_event:
                    on_event("sample_finished", sample)

    if include_api:
        for model in API_MODELS:
            if not has_key_for(model["spec"]):
                continue
            model_rows.append(dict(model))
            if on_event:
                on_event("model_started", model)
            for repeat in range(1, repeats + 1):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Эксперимент отменён")
                if on_event:
                    on_event("sample_started", {"model_id": model["id"], "repeat": repeat})
                sample = _run_api_sample(
                    model, repeat, prices.get(model["id"]), on_event, cancel_event
                )
                samples.append(sample)
                if on_event:
                    on_event("sample_finished", sample)

    resolved_local_url = local_url or os.environ.get("LOCAL_LLM_URL")
    resolved_ollama_url = ollama_url or os.environ.get("OLLAMA_URL")
    resolved_local_cpu_url = local_cpu_url or os.environ.get("LOCAL_CPU_LLM_URL")
    if include_local_cpu and resolved_local_cpu_url:
        local_cpu = _local_info(resolved_local_cpu_url)
        local_cpu_row = {
            **LOCAL_CPU,
            "repo": local_cpu["alias"],
            "parameters_b": local_cpu["parameters_b"],
            "details": local_cpu,
        }
        model_rows.append(local_cpu_row)
        if on_event:
            on_event("model_started", local_cpu_row)
        for repeat in range(1, repeats + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Эксперимент отменён")
            if on_event:
                on_event("sample_started", {"model_id": LOCAL_CPU["id"], "repeat": repeat})
            sample = _run_local_sample(
                resolved_local_cpu_url,
                local_cpu,
                repeat,
                model_id=LOCAL_CPU["id"],
                resource="cpu",
                on_event=on_event,
                cancel_event=cancel_event,
            )
            samples.append(sample)
            if on_event:
                on_event("sample_finished", sample)

    if include_local_small and resolved_ollama_url:
        local_small = _ollama_info(resolved_ollama_url, LOCAL_SMALL["repo"])
        local_small_row = {**LOCAL_SMALL, "details": local_small}
        model_rows.append(local_small_row)
        if on_event:
            on_event("model_started", local_small_row)
        sleeping = bool(resolved_local_url and _llamacpp_power(resolved_local_url, sleeping=True))
        try:
            for repeat in range(1, repeats + 1):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Эксперимент отменён")
                if on_event:
                    on_event("sample_started", {"model_id": LOCAL_SMALL["id"], "repeat": repeat})
                sample = _run_ollama_sample(
                    resolved_ollama_url, local_small, repeat, on_event, cancel_event
                )
                samples.append(sample)
                if on_event:
                    on_event("sample_finished", sample)
        finally:
            _unload_ollama(resolved_ollama_url, local_small["alias"])
            if sleeping:
                _llamacpp_power(resolved_local_url, sleeping=False)

    if include_local and resolved_local_url:
        local = _local_info(resolved_local_url)
        local_row = {
            "id": "local", "label": "LOCAL · 27B IQ4_XS",
            "repo": local["alias"], "parameters_b": local["parameters_b"],
            "details": local,
        }
        model_rows.append(local_row)
        if on_event:
            on_event("model_started", local_row)
        for repeat in range(1, repeats + 1):
            if on_event:
                on_event("sample_started", {"model_id": "local", "repeat": repeat})
            sample = _run_local_sample(
                resolved_local_url,
                local,
                repeat,
                model_id="local",
                resource="gpu",
                on_event=on_event,
                cancel_event=cancel_event,
            )
            samples.append(sample)
            if on_event:
                on_event("sample_finished", sample)

    metrics = _aggregate(samples, model_rows)
    return {
        "schema": "day5-model-versions-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "locked": {
            "prompt": PROMPT,
            "prompt_sha256": prompt_sha256(),
            "temperature": TEMPERATURE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "repeats": repeats,
            "hf_provider": HF_PROVIDER,
        },
        "models": model_rows,
        "price_snapshot": prices,
        "samples": samples,
        "metrics": metrics,
        "verdict": _verdict(metrics),
        "sources": [
            "https://huggingface.co/docs/inference-providers/index",
            "https://huggingface.co/docs/inference-providers/pricing",
            *[f"https://huggingface.co/{m['repo']}" for m in HF_MODELS],
            "https://huggingface.co/unsloth/Qwen3.8-27B-GGUF",
            "https://huggingface.co/Qwen/Qwen3-1.7B",
            "https://ollama.com/library/qwen3.5:4b",
            "https://ai.google.dev/gemini-api/docs/pricing",
            "https://api-docs.deepseek.com/quick_start/pricing/",
        ],
    }
