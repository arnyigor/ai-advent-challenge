"""Day 30 checks: run the documented contract against the running service.

Every check talks to the real gateway (default http://127.0.0.1:8091) and, where
the profile itself is the subject, to the real backend on loopback. Results are
written to evidence/day30-<stage>.json: statuses, timings, usage, finish_reason
and short answer excerpts. API keys are never written to evidence - only their
labels.

Stages (each is a separate run; the model is small and CPU-bound):

  python verify.py backend        # loopback model: alias, n_ctx, token-count equality, smoke
  python verify.py core           # contract over the gateway: auth, schema, history memory
  python verify.py load --count 20
  python verify.py concurrent --clients 3 --rounds 3
  python verify.py queue          # bounded queue: 503 on overflow, recovery afterwards
  python verify.py ratelimit      # 11th POST in a window -> 429 + Retry-After
  python verify.py context        # token-based context limit, accepted/rejected pair
  python verify.py budget         # max_tokens bounds and finish_reason=length
  python verify.py backend-down --expect-backend-down   # run while the model is stopped
  python verify.py report         # aggregate evidence/*.json
  python verify.py init-keys      # create keys.json with random keys (gitignored)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import string
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llmgateway import config  # noqa: E402

DAY_DIR = Path(__file__).resolve().parent
EVIDENCE = DAY_DIR / "evidence"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Recorder:
    """Collects one record per HTTP call and writes the stage evidence file."""

    def __init__(self, stage, gateway_url, backend_url, notes=None):
        self.stage = stage
        self.gateway_url = gateway_url
        self.backend_url = backend_url
        self.started = now()
        self.records = []
        self.notes = notes or []
        self.expectations = []

    def add(self, **fields):
        self.records.append(fields)
        return fields

    def expect(self, name, ok, detail=""):
        self.expectations.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'ok' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
        return bool(ok)

    def write(self):
        by_status = {}
        for record in self.records:
            by_status[str(record.get("status"))] = by_status.get(str(record.get("status")), 0) + 1
        wall = [r["wall_ms"] for r in self.records if isinstance(r.get("wall_ms"), (int, float))]
        generations = [
            r["generation_ms"] for r in self.records if isinstance(r.get("generation_ms"), (int, float))
        ]
        waits = [r["queue_ms"] for r in self.records if isinstance(r.get("queue_ms"), (int, float))]
        summary = {
            "calls": len(self.records),
            "by_status": by_status,
            "unexpected_errors": [
                r for r in self.records if r.get("unexpected") and isinstance(r.get("status"), int) and r["status"] >= 500
            ],
            "failed_expectations": [e for e in self.expectations if not e["ok"]],
            "wall_ms": {
                "median": round(statistics.median(wall)) if wall else None,
                "max": max(wall) if wall else None,
            },
            "generation_ms": {
                "median": round(statistics.median(generations)) if generations else None,
                "max": max(generations) if generations else None,
            },
            "queue_ms": {
                "median": round(statistics.median(waits)) if waits else None,
                "max": max(waits) if waits else None,
            },
        }
        payload = {
            "stage": self.stage,
            "day": 30,
            "started_at": self.started,
            "finished_at": now(),
            "gateway_url": self.gateway_url,
            "backend_url": self.backend_url,
            "profile": {
                "model_alias": config.MODEL_ALIAS,
                "context_window": config.CONTEXT_WINDOW,
                "context_margin_tokens": config.CONTEXT_MARGIN_TOKENS,
                "parallel_slots": config.PARALLEL_SLOTS,
                "backend_api_key": bool(config.model_api_key()),
                "max_tokens": {"min": config.MIN_MAX_TOKENS, "max": config.MAX_MAX_TOKENS},
                "rate_limit": {"requests": config.RATE_LIMIT_REQUESTS, "window_sec": config.RATE_LIMIT_WINDOW_SEC},
                "queue": {"max_waiting": config.MAX_WAITING_REQUESTS, "wait_timeout_sec": config.QUEUE_WAIT_TIMEOUT_SEC},
            },
            "notes": self.notes,
            "expectations": self.expectations,
            "summary": summary,
            "calls": self.records,
        }
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        path = EVIDENCE / f"day30-{self.stage}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{self.stage}: {summary['calls']} calls, statuses {by_status}, "
              f"failed expectations: {len(summary['failed_expectations'])}")
        print(f"evidence -> {path.relative_to(DAY_DIR)}")
        return not summary["failed_expectations"]


def post_chat(client, key, messages, max_tokens=config.DEFAULT_MAX_TOKENS, model=None, extra=None, expected=None):
    """One POST /v1/chat/completions. Returns (status, body, headers, wall_ms)."""
    payload = {"model": model or config.MODEL_ALIAS, "messages": messages, "max_tokens": max_tokens}
    if extra:
        payload.update(extra)
    started = time.perf_counter()
    try:
        response = client.post("/v1/chat/completions", json=payload, headers=auth_headers(key))
        wall_ms = round((time.perf_counter() - started) * 1000)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:200]}
    except httpx.HTTPError as exc:
        wall_ms = round((time.perf_counter() - started) * 1000)
        return None, {"network_error": str(exc)}, {}, wall_ms
    status = response.status_code
    return status, body, dict(response.headers), wall_ms


def auth_headers(key):
    return {"Authorization": f"Bearer {key}"} if key else {}


def backend_headers():
    """Bearer for the loopback model when it was started with --api-key."""
    key = config.model_api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def record_chat(recorder, label, status, body, headers, wall_ms, expected, **extra):
    if status is None:
        recorder.add(call=label, key_label=extra.pop("key_label", None), status="network_error",
                     wall_ms=wall_ms, unexpected=True, **extra)
        return
    error = (body or {}).get("error") or {}
    choice = ((body or {}).get("choices") or [{}])[0]
    usage = (body or {}).get("usage") or {}
    answer = ((choice.get("message") or {}).get("content") or "")
    recorder.add(
        call=label,
        key_label=extra.pop("key_label", None),
        request_id=(body or {}).get("request_id") or headers.get("x-request-id"),
        status=status,
        wall_ms=wall_ms,
        queue_ms=extra.pop("queue_ms", None),
        generation_ms=extra.pop("generation_ms", None),
        error_code=error.get("code"),
        error_message=error.get("message"),
        retry_after=headers.get("retry-after"),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        finish_reason=choice.get("finish_reason"),
        answer_excerpt=answer[:300],
        unexpected=status != expected,
        **extra,
    )


def token_count(backend_client, messages):
    """Exact prompt tokens via the backend chat template + tokenizer."""
    rendered = backend_client.post("/apply-template", json={"messages": messages})
    rendered.raise_for_status()
    prompt = rendered.json()["prompt"]
    tokenized = backend_client.post("/tokenize", json={"content": prompt})
    tokenized.raise_for_status()
    return len(tokenized.json()["tokens"]), prompt


def filler_for_tokens(backend_client, target, messages_prefix,
                      unit="алгоритм проверки контекста и границ окна. "):
    """Grow a filler message until the rendered prompt reaches ~target tokens.

    Token-per-unit is measured first (repeating text merges in BPE), then the
    length is corrected by measurement, never by character counting.
    """
    base = token_count(backend_client, messages_prefix + [{"role": "user", "content": "x"}])[0]
    per_unit = token_count(backend_client, messages_prefix + [{"role": "user", "content": unit}])[0] - base
    if per_unit <= 0:
        raise RuntimeError(f"filler unit does not grow the prompt (base={base})")
    n = max(int((target - base) // per_unit), 1)
    messages = messages_prefix + [{"role": "user", "content": unit * n}]
    count = token_count(backend_client, messages)[0]
    for _ in range(60):
        if abs(count - target) <= per_unit:
            return messages, count
        if count < target:
            n += max(int((target - count) // per_unit), 1)
        else:
            n = max(n - max(int((count - target) // per_unit), 1), 1)
        messages = messages_prefix + [{"role": "user", "content": unit * n}]
        count = token_count(backend_client, messages)[0]
    raise RuntimeError(f"could not reach {target} prompt tokens (stopped at {count})")


# --------------------------------------------------------------------------- stages
def ensure_window(client, key, recorder, label):
    """Probe a key's rate-limit bucket and wait out the window if it is dirty.

    The rate limit is per key and the bucket lives in memory, so a stage re-run
    within 60 s would otherwise be rejected with 429 before reaching its subject.
    """
    for attempt in range(3):
        status, body, headers, wall_ms = post_chat(client, key, [{"role": "user", "content": "Ответь: ок."}],
                                                   max_tokens=8)
        record_chat(recorder, f"window probe ({label})", status, body, headers, wall_ms, 200, key_label=label)
        if status == 200:
            return True
        if status == 429 and attempt < 2:
            wait = float(headers.get("retry-after") or 5) + 1.0
            print(f"  bucket '{label}' was not empty: waiting {wait:.0f}s for a clean window")
            time.sleep(wait)
            continue
        return False
    return False


def stage_init_keys(_args, _recorder):
    path = DAY_DIR / "keys.json"
    if path.exists() and not _args.force:
        print(f"{path} already exists; use --force to replace")
        return 0
    alphabet = string.ascii_letters + string.digits
    keys = {label: "-".join("".join(random.choice(alphabet) for _ in range(16)) for _ in range(3))
            for label in ("main", "ratelimit", "load", "concurrent", "queue", "tests")}
    model_key = "-".join("".join(random.choice(alphabet) for _ in range(16)) for _ in range(3))
    path.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")
    model_key_file = DAY_DIR / "model-key.txt"
    model_key_file.write_text(model_key, encoding="utf-8")
    try:
        path.chmod(0o600)
        model_key_file.chmod(0o600)
    except OSError:
        pass
    print(f"wrote {path} with labels: {', '.join(keys)} (file is gitignored; keys are not printed)")
    return 0


def stage_backend(args, recorder):
    """The profile itself: alias, window, one slot, token counting against a real request."""
    model_key = config.model_api_key()
    with httpx.Client(base_url=args.backend_url, timeout=300, headers=backend_headers()) as backend:
        props_response = backend.get("/props")
        if props_response.status_code != 200:
            recorder.add(call="backend:/props", status=props_response.status_code,
                         error=props_response.text[:200])
            recorder.expect("the backend accepts the gateway's model key", False,
                            f"HTTP {props_response.status_code}: restart the model after rotating "
                            "model-key.txt, or clear MODEL_API_KEY on both sides")
            return 1
        props = props_response.json()
        n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
        slots = props.get("total_slots")
        recorder.add(call="backend:/props", status=200, model_alias=props.get("model_alias"),
                     n_ctx=n_ctx, total_slots=slots, chat_template_present=bool(props.get("chat_template")))
        recorder.expect("backend alias is day30-qwen3-1.7b", props.get("model_alias") == config.MODEL_ALIAS,
                        f"alias={props.get('model_alias')}")
        recorder.expect(f"backend context window is {config.CONTEXT_WINDOW}", n_ctx == config.CONTEXT_WINDOW,
                        f"n_ctx={n_ctx}")
        recorder.expect("backend has one slot", slots == config.PARALLEL_SLOTS, f"total_slots={slots}")

        models = backend.get("/v1/models").json()
        alias = models["data"][0]["id"] if models.get("data") else None
        recorder.expect("model listing matches the alias", alias == config.MODEL_ALIAS, f"id={alias}")

        # Direct access to the model must not work without the model key.
        recorder.add(call="backend: key configured", status=200, model_api_key=bool(model_key))
        if model_key:
            with httpx.Client(base_url=args.backend_url, timeout=60) as open_client:
                direct = {}
                for path in ("/props", "/v1/models"):
                    response = open_client.get(path)
                    direct[path] = response.status_code
                response = open_client.post("/v1/chat/completions", json={
                    "model": config.MODEL_ALIAS, "messages": [{"role": "user", "content": "привет"}],
                    "max_tokens": 4})
                direct["/v1/chat/completions"] = response.status_code
                recorder.add(call="backend: direct calls without the model key", status=200, statuses=direct)
                recorder.expect("direct backend calls without the model key -> 401",
                                all(code == 401 for code in direct.values()), f"statuses={direct}")
                recorder.notes.append(
                    "llama-server запущен с --api-key, поэтому шлюз — единственный держатель ключа; "
                    "/health остаётся открытым для проверки готовности."
                )
        else:
            recorder.notes.append("MODEL_API_KEY не задан: backend открыт для локальных процессов (только loopback).")

        messages = [{"role": "system", "content": config.SYSTEM_PROMPT},
                    {"role": "user", "content": "Назови три цвета. Кратко."}]
        counted, _ = token_count(backend, messages)
        started = time.perf_counter()
        response = backend.post("/v1/chat/completions", json={
            "model": config.MODEL_ALIAS, "messages": messages, "max_tokens": 64, "temperature": 0})
        wall_ms = round((time.perf_counter() - started) * 1000)
        body = response.json()
        usage = body.get("usage", {})
        recorder.add(call="backend:chat", status=response.status_code, wall_ms=wall_ms,
                     counted_prompt_tokens=counted, prompt_tokens=usage.get("prompt_tokens"),
                     completion_tokens=usage.get("completion_tokens"),
                     finish_reason=body["choices"][0]["finish_reason"],
                     answer_excerpt=body["choices"][0]["message"]["content"][:300])
        recorder.expect("apply-template + tokenize equals usage.prompt_tokens",
                        counted == usage.get("prompt_tokens"),
                        f"counted={counted} reported={usage.get('prompt_tokens')}")
        recorder.expect("smoke answer is not empty",
                        bool(body["choices"][0]["message"]["content"].strip()))
        return 0


def stage_core(args, recorder):
    keys = config.load_keys()
    main = keys.get("tests") or keys.get("main") or next(iter(keys.values()))
    with httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        ensure_window(client, main, recorder, "tests")
        health = client.get("/health")
        recorder.add(call="GET /health", status=health.status_code, body=health.json())
        recorder.expect("health reports ready backend", health.status_code == 200
                        and health.json().get("status") == "ok", f"HTTP {health.status_code}")
        limits_body = client.get("/limits").json()
        recorder.expect("gateway advertises the same window as config",
                        limits_body.get("context_window") == config.CONTEXT_WINDOW
                        and limits_body.get("max_tokens", {}).get("max") == config.MAX_MAX_TOKENS)

        for label, key in (("no key", None), ("wrong key", "definitely-not-a-key")):
            response = client.get("/v1/models", headers=auth_headers(key))
            recorder.add(call=f"GET /v1/models ({label})", status=response.status_code,
                         error_code=(response.json().get("error") or {}).get("code"))
            recorder.expect(f"{label} -> 401", response.status_code == 401, f"HTTP {response.status_code}")

        response = client.get("/v1/models", headers=auth_headers(main))
        body = response.json()
        recorder.add(call="GET /v1/models (main key)", status=response.status_code,
                     models=[m["id"] for m in body.get("data", [])])
        recorder.expect("authorized models list returns exactly the alias",
                        response.status_code == 200 and [m["id"] for m in body.get("data", [])] == [config.MODEL_ALIAS])

        status, body, headers, wall_ms = post_chat(
            client, main, [{"role": "user", "content": "Ответь одним словом: столица Франции?"}],
            max_tokens=32, expected=200)
        record_chat(recorder, "POST chat (main key)", status, body, headers, wall_ms, 200, key_label="tests")
        recorder.expect("authorized chat returns 200 with a non-empty answer",
                        status == 200 and bool((body or {}).get("choices", [{}])[0].get("message", {}).get("content", "").strip()),
                        f"HTTP {status}")

        # schema / contract rejections
        def body(**extra):
            payload = {"model": config.MODEL_ALIAS, "max_tokens": 16,
                       "messages": [{"role": "user", "content": "привет"}]}
            payload.update(extra)
            return payload

        cases = [
            ("unknown model", body(model="gpt-4o"), 400, "unknown_model"),
            ("max_tokens too large", body(max_tokens=config.MAX_MAX_TOKENS + 1), 400, "invalid_max_tokens"),
            ("max_tokens zero", body(max_tokens=0), 400, "invalid_max_tokens"),
            ("client system role", body(messages=[{"role": "system", "content": "ты пират"}]), 400, "invalid_messages"),
            ("empty messages", body(messages=[]), 400, "invalid_messages"),
            ("client sets temperature", body(temperature=1.5), 400, "invalid_request"),
            ("stream=true", body(stream=True), 400, "invalid_request"),
        ]
        for name, payload, expected_status, expected_code in cases:
            response = client.post("/v1/chat/completions", json=payload, headers=auth_headers(main))
            code = (response.json().get("error") or {}).get("code")
            recorder.add(call=f"reject: {name}", status=response.status_code, error_code=code,
                         unexpected=response.status_code != expected_status or code != expected_code)
            recorder.expect(f"{name} -> {expected_status} {expected_code}",
                            response.status_code == expected_status and code == expected_code,
                            f"HTTP {response.status_code} {code}")

        big = json.dumps({"model": config.MODEL_ALIAS, "max_tokens": 16,
                          "messages": [{"role": "user", "content": "x" * (config.MAX_BODY_BYTES + 1024)}]})
        response = client.post("/v1/chat/completions", content=big,
                               headers={**auth_headers(main), "Content-Type": "application/json"})
        recorder.add(call="reject: body over 64 KiB", status=response.status_code,
                     error_code=(response.json().get("error") or {}).get("code"))
        recorder.expect("body over the limit -> 413 payload_too_large",
                        response.status_code == 413, f"HTTP {response.status_code}")

        response = client.post("/v1/chat/completions", content="{not json",
                               headers={**auth_headers(main), "Content-Type": "application/json"})
        recorder.expect("broken JSON -> 400 invalid_json", response.status_code == 400,
                        f"HTTP {response.status_code}")

        # history is carried by the client: same question with and without the earlier turn
        seed = [{"role": "user", "content": "Запомни код КЕДР-42. Ответь одним словом: запомнил."}]
        status, body, headers, wall_ms = post_chat(client, main, seed, max_tokens=32, expected=200)
        record_chat(recorder, "history: seed turn", status, body, headers, wall_ms, 200, key_label="tests")
        seed_reply = ((body or {}).get("choices", [{}])[0].get("message", {}) or {}).get("content", "")

        with_history = seed + [{"role": "assistant", "content": seed_reply},
                               {"role": "user", "content": "Какой код я просил запомнить? Ответь код."}]
        status, body, headers, wall_ms = post_chat(client, main, with_history, max_tokens=48, expected=200)
        record_chat(recorder, "history: question with history", status, body, headers, wall_ms, 200, key_label="tests")
        answer_with = ((body or {}).get("choices", [{}])[0].get("message", {}) or {}).get("content", "")

        status, body, headers, wall_ms = post_chat(
            client, main, [{"role": "user", "content": "Какой код я просил запомнить? Ответь код."}],
            max_tokens=48, expected=200)
        record_chat(recorder, "history: same question without history", status, body, headers, wall_ms, 200,
                    key_label="tests")
        answer_without = ((body or {}).get("choices", [{}])[0].get("message", {}) or {}).get("content", "")

        recorder.add(call="history: verdict", status=200, with_history=answer_with[:300],
                     without_history=answer_without[:300],
                     code_with="КЕДР-42" in answer_with, code_without="КЕДР-42" in answer_without)
        recorder.expect("history reaches the model: the code appears with history",
                        "КЕДР-42" in answer_with, repr(answer_with[:80]))
        recorder.expect("control: the code does not appear without history",
                        "КЕДР-42" not in answer_without, repr(answer_without[:80]))
        recorder.notes.append(
            "История не хранится на сервере: клиент отправляет её с каждым запросом, поэтому пара "
            "«с историей / без истории» и есть доказательство передачи."
        )

        health_after = client.get("/health")
        recorder.expect("health after the contract checks", health_after.status_code == 200)
    return 0


def stage_load(args, recorder):
    keys = config.load_keys()
    key = keys.get("load") or keys.get("main") or next(iter(keys.values()))
    interval = args.interval
    with httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        ensure_window(client, key, recorder, "load")
        time.sleep(interval)  # the window probe is an accepted request too: keep even spacing
        for index in range(args.count):
            prompt = f"Ответь ровно одним коротким предложением, номер запроса {index + 1}."
            status, body, headers, wall_ms = post_chat(client, key, [{"role": "user", "content": prompt}],
                                                      max_tokens=args.max_tokens, expected=200)
            record_chat(recorder, f"load #{index + 1}", status, body, headers, wall_ms, 200, key_label="load")
            if status != 200:
                print(f"  #{index + 1}: HTTP {status} {(body.get('error') or {}).get('code')}")
            else:
                choice = body["choices"][0]
                print(f"  #{index + 1}: 200, {wall_ms} ms, {body['usage']['completion_tokens']} tok, "
                      f"{choice['finish_reason']}")
            if index < args.count - 1:
                time.sleep(interval)
        health = client.get("/health")
        recorder.expect("service is healthy after the sequential run", health.status_code == 200)
    load_records = [r for r in recorder.records if str(r.get("call", "")).startswith("load #")]
    statuses = [r.get("status") for r in load_records]
    recorder.expect(f"all {args.count} accepted requests finished with 200",
                    len(load_records) == args.count and all(s == 200 for s in statuses),
                    f"statuses={statuses}")
    truncated = [r for r in load_records if r.get("finish_reason") == "length"]
    lengths = [r.get("completion_tokens") for r in load_records if r.get("completion_tokens") is not None]
    corrections = [r for r in load_records if r.get("finish_reason") == "stop" and (r.get("completion_tokens") or 0) == 0]
    recorder.notes.append(f"truncated by max_tokens: {len(truncated)}; empty answers: {len(corrections)}")
    if lengths:
        recorder.add(call="load: completion tokens", status=200, median=round(statistics.median(lengths)),
                     max=max(lengths), truncated=len(truncated))
    return 0


def stage_concurrent(args, recorder):
    """Overlapping HTTP requests: one generation at a time, all accepted, no mixed history."""
    keys = config.load_keys()
    key = keys.get("concurrent") or keys.get("load") or next(iter(keys.values()))
    with httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        ensure_window(client, key, recorder, "concurrent")
        for round_index in range(args.rounds):
            if round_index:
                time.sleep(args.round_gap)  # keep the 9 accepted requests inside one clean window
            tag = 100 + round_index * 10
            results = {}
            pending = []
            for client_index in range(args.clients):
                pending.append((tag + client_index, f"Ответь ровно одной строкой: TAG-{tag + client_index}"))
            with httpx.Client(base_url=args.gateway_url, timeout=300) as pool:
                # fire all at once, then collect
                import threading

                lock = threading.Lock()

                def worker(expected_tag, prompt):
                    status, body, headers, wall_ms = post_chat(
                        pool, key, [{"role": "user", "content": prompt}], max_tokens=32, expected=200)
                    with lock:
                        results[expected_tag] = (status, body, headers, wall_ms)

                threads = [threading.Thread(target=worker, args=item) for item in pending]
                started = time.perf_counter()
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                round_wall = round((time.perf_counter() - started) * 1000)

            wrong_history = 0
            statuses = []
            for expected_tag, _prompt in pending:
                status, body, headers, wall_ms = results[expected_tag]
                answer = ((body or {}).get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
                statuses.append(status)
                if status == 200 and f"TAG-{expected_tag}" not in answer:
                    wrong_history += 1
                record_chat(recorder, f"concurrent r{round_index + 1} TAG-{expected_tag}", status, body, headers,
                            wall_ms, 200, key_label="concurrent", expected_tag=expected_tag,
                            answer_has_tag=f"TAG-{expected_tag}" in answer)
            recorder.add(call=f"concurrent round {round_index + 1}", status=200, round_wall_ms=round_wall,
                         statuses=statuses, wrong_tag=wrong_history)
            print(f"  round {round_index + 1}: {round_wall} ms, statuses {statuses}, wrong tag {wrong_history}")
            recorder.expect(f"round {round_index + 1}: all {args.clients} requests answered", all(s == 200 for s in statuses),
                            f"statuses={statuses}")
            recorder.expect(f"round {round_index + 1}: every answer carries its own tag", wrong_history == 0,
                            f"mismatched={wrong_history}")
    recorder.notes.append(
        "Одновременный приём запросов не равен одновременной генерации: backend имеет один слот "
        "(total_slots=1), поэтому запросы обслуживаются последовательно."
    )
    return 0


def stage_queue(args, recorder):
    """Bounded queue: one active generation, three waiters, the fifth request gets 503."""
    keys = config.load_keys()
    key = keys.get("queue") or keys.get("load") or keys.get("main") or next(iter(keys.values()))
    with httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        ensure_window(client, key, recorder, "queue")

        def wait_for(predicate, timeout, what):
            deadline = time.time() + timeout
            while time.time() < deadline:
                stats = client.get("/health").json().get("queue", {})
                if predicate(stats):
                    return stats
                time.sleep(0.1)
            raise TimeoutError(f"queue never reached: {what}")

        import threading

        results = {}
        lock = threading.Lock()

        def worker(name, prompt, max_tokens):
            status, body, headers, wall_ms = post_chat(client, key, [{"role": "user", "content": prompt}],
                                                       max_tokens=max_tokens)
            with lock:
                results[name] = (status, body, headers, wall_ms)

        long_thread = threading.Thread(
            target=worker,
            args=("long", "Напиши подробный текст о зиме, не менее 200 слов.", 400),
        )
        long_thread.start()
        stats = wait_for(lambda s: s.get("active"), 30, "an active generation")
        recorder.add(call="queue: active observed", status=200, queue=stats)

        waiters = []
        for index in range(config.MAX_WAITING_REQUESTS):
            thread = threading.Thread(target=worker, args=(f"waiter{index + 1}", "Скажи одно слово.", 16))
            waiters.append(thread)
            thread.start()
            time.sleep(0.3)
        stats = wait_for(lambda s: s.get("waiting") >= config.MAX_WAITING_REQUESTS, 30, "waiting room full")
        recorder.add(call="queue: waiting room full", status=200, queue=stats)

        status, body, headers, wall_ms = post_chat(client, key, [{"role": "user", "content": "Скажи одно слово."}],
                                                   max_tokens=16)
        code = (body.get("error") or {}).get("code")
        record_chat(recorder, "queue: overflow request", status, body, headers, wall_ms, 503, key_label="queue")
        recorder.expect("queue overflow -> 503 queue_full with Retry-After",
                        status == 503 and code == "queue_full" and headers.get("retry-after") is not None,
                        f"HTTP {status} {code} Retry-After={headers.get('retry-after')}")

        long_thread.join()
        for thread in waiters:
            thread.join()
        for name in ("long", "waiter1", "waiter2", "waiter3"):
            status, body, headers, wall_ms = results[name]
            record_chat(recorder, f"queue: {name}", status, body, headers, wall_ms, 200, key_label="queue")
        recorder.expect("all accepted requests finished after the overflow",
                        all(results[name][0] == 200 for name in results), f"statuses={[results[n][0] for n in results]}")

        status, body, headers, wall_ms = post_chat(client, key, [{"role": "user", "content": "Скажи одно слово."}],
                                                   max_tokens=16, expected=200)
        record_chat(recorder, "queue: recovery request", status, body, headers, wall_ms, 200, key_label="queue")
        recorder.expect("after the queue drains the service answers again", status == 200, f"HTTP {status}")
    return 0


def stage_ratelimit(args, recorder):
    keys = config.load_keys()
    key = keys.get("ratelimit")
    if not key:
        print("no 'ratelimit' label in the keys file; add one so the demo does not disturb the chat key")
        return 1
    with httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        # A re-run inside the window would start with 429; wait for a clean bucket first.
        for attempt in range(3):
            status, body, headers, wall_ms = post_chat(client, key, [{"role": "user", "content": "Ответь: да."}],
                                                      max_tokens=8)
            if status == 200:
                break
            recorder.add(call=f"ratelimit: dirty-window probe {attempt + 1}", status=status,
                         error_code=(body.get("error") or {}).get("code"),
                         retry_after=headers.get("retry-after"))
            wait = float(headers.get("retry-after") or 5) + 1.0
            print(f"  bucket was not empty (HTTP {status}); waiting {wait:.0f}s for a clean window")
            time.sleep(wait)
        else:
            recorder.expect("a clean rate-limit window could be obtained", False, "bucket stayed busy")
            return 1

        statuses = [status]
        record_chat(recorder, "ratelimit #1", status, body, headers, wall_ms, 200, key_label="ratelimit")
        for index in range(1, config.RATE_LIMIT_REQUESTS + 1):
            status, body, headers, wall_ms = post_chat(client, key, [{"role": "user", "content": "Ответь: да."}],
                                                      max_tokens=8)
            code = (body.get("error") or {}).get("code")
            statuses.append(status)
            record_chat(recorder, f"ratelimit #{index + 1}", status, body, headers, wall_ms,
                        200 if index < config.RATE_LIMIT_REQUESTS else 429, key_label="ratelimit")
            print(f"  #{index + 1}: HTTP {status}" + (f" {code} Retry-After={headers.get('retry-after')}" if code else ""))
        recorder.expect(f"first {config.RATE_LIMIT_REQUESTS} requests pass",
                        statuses[:config.RATE_LIMIT_REQUESTS] == [200] * config.RATE_LIMIT_REQUESTS,
                        f"statuses={statuses[:config.RATE_LIMIT_REQUESTS]}")
        last = recorder.records[-1]
        recorder.expect("11th request -> 429 rate_limited with Retry-After",
                        last.get("status") == 429 and last.get("error_code") == "rate_limited"
                        and last.get("retry_after") is not None,
                        f"HTTP {last.get('status')} {last.get('error_code')} Retry-After={last.get('retry_after')}")
        retry_after = float(last.get("retry_after") or 0)
        print(f"  waiting {retry_after:.0f}s for the window to slide")
        time.sleep(retry_after + 1.0)
        status, body, headers, wall_ms = post_chat(client, key, [{"role": "user", "content": "Ответь: да."}],
                                                   max_tokens=8, expected=200)
        record_chat(recorder, "ratelimit: after the window", status, body, headers, wall_ms, 200, key_label="ratelimit")
        recorder.expect("after the window the same key passes again", status == 200, f"HTTP {status}")
    return 0


def stage_context(args, recorder):
    """Accepted/rejected pair decided by real token counts, not by character guesses."""
    keys = config.load_keys()
    main = keys.get("main") or next(iter(keys.values()))
    with httpx.Client(base_url=args.backend_url, timeout=300, headers=backend_headers()) as backend, \
            httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        ensure_window(client, main, recorder, "main")
        margin = config.CONTEXT_MARGIN_TOKENS
        low_target = config.CONTEXT_WINDOW - 200
        # The prompt is counted with the server's own system message, but only
        # user/assistant turns are sent: the gateway rejects client system roles.
        counted_low_messages, counted_low = filler_for_tokens(
            backend, low_target, [{"role": "system", "content": config.SYSTEM_PROMPT}])
        messages_low = counted_low_messages[1:]
        status, body, headers, wall_ms = post_chat(client, main, messages_low, max_tokens=16, expected=200)
        record_chat(recorder, "context: just below the boundary", status, body, headers, wall_ms, 200,
                    key_label="main", counted_prompt_tokens=counted_low)
        recorder.add(call="context: below boundary math", status=200, prompt_tokens=counted_low, max_tokens=16,
                     required=counted_low + 16 + margin, window=config.CONTEXT_WINDOW)
        recorder.expect("prompt close to the window still passes when the answer fits",
                        status == 200, f"counted={counted_low} HTTP {status}")

        high_target = config.CONTEXT_WINDOW - 100
        counted_high_messages, counted_high = filler_for_tokens(
            backend, high_target, [{"role": "system", "content": config.SYSTEM_PROMPT}])
        messages_high = counted_high_messages[1:]
        status, body, headers, wall_ms = post_chat(client, main, messages_high, max_tokens=256, expected=400)
        code = (body.get("error") or {}).get("code")
        record_chat(recorder, "context: prompt + answer over the boundary", status, body, headers, wall_ms, 400,
                    key_label="main", counted_prompt_tokens=counted_high)
        recorder.add(call="context: above boundary math", status=200, prompt_tokens=counted_high, max_tokens=256,
                     required=counted_high + 256 + margin, window=config.CONTEXT_WINDOW)
        recorder.expect("prompt + max_tokens + margin over the window -> 400 context_limit before inference",
                        status == 400 and code == "context_limit", f"HTTP {status} {code}")
        recorder.expect("rejection happens fast: no generation was started", wall_ms < 2000, f"{wall_ms} ms")
        recorder.notes.append(
            "История не обрезается молча: превышение возвращает context_limit, клиент сам решает, что сокращать."
        )
    return 0


def stage_budget(args, recorder):
    keys = config.load_keys()
    main = keys.get("main") or next(iter(keys.values()))
    with httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        ensure_window(client, main, recorder, "main")
        status, body, headers, wall_ms = post_chat(client, main, [{"role": "user", "content": "Ответь: да."}],
                                                   max_tokens=1, expected=200)
        record_chat(recorder, "budget: max_tokens=1", status, body, headers, wall_ms, 200, key_label="main")
        recorder.expect("max_tokens=1 is accepted", status == 200, f"HTTP {status}")

        status, body, headers, wall_ms = post_chat(
            client, main, [{"role": "user", "content": "Перечисли подробно все времена года и месяцы."}],
            max_tokens=16, expected=200)
        record_chat(recorder, "budget: truncation visible", status, body, headers, wall_ms, 200, key_label="main")
        finish = ((body or {}).get("choices", [{}])[0].get("finish_reason"))
        recorder.expect("truncation is reported as finish_reason=length", finish == "length", f"finish_reason={finish}")
        recorder.notes.append(
            "finish_reason=length — ответ обрезан лимитом генерации, а не контекстом: входной контекст "
            "проверяется отдельно (стадия context)."
        )
    return 0


def stage_backend_down(args, recorder):
    keys = config.load_keys()
    main = keys.get("main") or next(iter(keys.values()))
    with httpx.Client(base_url=args.gateway_url, timeout=60) as client:
        health = client.get("/health")
        recorder.add(call="GET /health with the model stopped", status=health.status_code, body=health.json())
        recorder.expect("health reports 503 while the backend is down", health.status_code == 503,
                        f"HTTP {health.status_code}")
        status, body, headers, wall_ms = post_chat(client, main, [{"role": "user", "content": "привет"}],
                                                   max_tokens=16, expected=503)
        code = (body.get("error") or {}).get("code")
        record_chat(recorder, "chat with the model stopped", status, body, headers, wall_ms, 503, key_label="main")
        recorder.expect("chat returns a clear 503 backend_unavailable, no traceback",
                        status == 503 and code == "backend_unavailable" and "Traceback" not in json.dumps(body),
                        f"HTTP {status} {code}")
        if args.expect_backend_down:
            recorder.notes.append("Прогон выполнялся при остановленном llama-server (остановлен вручную).")
    return 0


def stage_backend_up(args, recorder):
    keys = config.load_keys()
    main = keys.get("main") or next(iter(keys.values()))
    with httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        health = client.get("/health")
        recorder.add(call="GET /health after restart", status=health.status_code, body=health.json())
        recorder.expect("health is ready again after the model restarted", health.status_code == 200,
                        f"HTTP {health.status_code}")
        status, body, headers, wall_ms = post_chat(client, main, [{"role": "user", "content": "Ответь: работает."}],
                                                   max_tokens=16, expected=200)
        record_chat(recorder, "chat after restart", status, body, headers, wall_ms, 200, key_label="main")
        recorder.expect("a new request succeeds after recovery", status == 200, f"HTTP {status}")
    return 0


def stage_network(args, recorder):
    """Address check: the gateway answers on the address it was bound to.

    Run with --gateway-url http://<LAN-IP>:8090 after starting the service with
    -BindHost <LAN-IP>. From this machine this proves the bind and reachability;
    the real LAN proof is a request from a second device (see README, not verified
    here unless the notes say otherwise).
    """
    keys = config.load_keys()
    main = keys.get("tests") or keys.get("main") or next(iter(keys.values()))
    with httpx.Client(base_url=args.gateway_url, timeout=300) as client:
        health = client.get("/health")
        recorder.add(call=f"GET /health via {args.gateway_url}", status=health.status_code,
                     body=health.json() if health.status_code else None)
        recorder.expect(f"health answers on {args.gateway_url}", health.status_code == 200,
                        f"HTTP {health.status_code}")
        ensure_window(client, main, recorder, "tests")
        models = client.get("/v1/models", headers=auth_headers(main))
        recorder.add(call="GET /v1/models via the bind address", status=models.status_code)
        recorder.expect("authorized models call works on the bind address", models.status_code == 200,
                        f"HTTP {models.status_code}")
        unauthorized = client.get("/v1/models")
        recorder.expect("the bind address still requires a key", unauthorized.status_code == 401,
                        f"HTTP {unauthorized.status_code}")
        status, body, headers, wall_ms = post_chat(client, main,
                                                   [{"role": "user", "content": "Ответь: доступ есть."}],
                                                   max_tokens=16, expected=200)
        record_chat(recorder, "chat via the bind address", status, body, headers, wall_ms, 200, key_label="tests")
        recorder.expect("a real generation works on the bind address", status == 200, f"HTTP {status}")
        recorder.notes.append(
            f"Запросы отправлены на {args.gateway_url} с этого же компьютера: это доказывает bind, "
            "но не заменяет запрос со второго устройства."
        )
    return 0


def stage_report(_args, _recorder):
    stages = []
    for path in sorted(EVIDENCE.glob("day30-*.json")):
        if path.name == "day30-summary.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        stages.append({
            "stage": data["stage"],
            "calls": data["summary"]["calls"],
            "by_status": data["summary"]["by_status"],
            "failed_expectations": len(data["summary"]["failed_expectations"]),
            "wall_ms_median": data["summary"]["wall_ms"]["median"],
            "wall_ms_max": data["summary"]["wall_ms"]["max"],
            "generation_ms_median": data["summary"]["generation_ms"]["median"],
            "queue_ms_max": data["summary"]["queue_ms"]["max"],
        })
    print(f"{'stage':<14}{'calls':>6}{'statuses':>28}{'failed':>8}{'wall med/max':>16}")
    for row in stages:
        statuses = ", ".join(f"{k}:{v}" for k, v in sorted(row["by_status"].items()))
        print(f"{row['stage']:<14}{row['calls']:>6}{statuses:>28}{row['failed_expectations']:>8}"
              f"{str(row['wall_ms_median']) + '/' + str(row['wall_ms_max']):>16}")
    payload = {"day": 30, "generated_at": now(), "stages": stages,
               "total_calls": sum(row["calls"] for row in stages),
               "failed_expectations": sum(row["failed_expectations"] for row in stages)}
    (EVIDENCE / "day30-summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ntotal calls: {payload['total_calls']}, failed expectations: {payload['failed_expectations']}")
    print(f"evidence -> evidence/day30-summary.json")
    return 0 if payload["failed_expectations"] == 0 else 1


STAGES = {
    "backend": stage_backend,
    "core": stage_core,
    "load": stage_load,
    "concurrent": stage_concurrent,
    "queue": stage_queue,
    "ratelimit": stage_ratelimit,
    "context": stage_context,
    "budget": stage_budget,
    "backend-down": stage_backend_down,
    "backend-up": stage_backend_up,
    "network": stage_network,
    "report": stage_report,
}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=[*STAGES, "init-keys", "all"])
    parser.add_argument("--gateway-url", default=os.environ.get("GATEWAY_URL", "http://127.0.0.1:8091"))
    parser.add_argument("--backend-url", default=os.environ.get("BACKEND_URL", config.BACKEND_URL))
    parser.add_argument("--count", type=int, default=20, help="requests for the load stage")
    parser.add_argument("--interval", type=float, default=6.2, help="pause between load requests, seconds")
    parser.add_argument("--max-tokens", type=int, default=16, help="generation cap for the load stage")
    parser.add_argument("--clients", type=int, default=3)
    parser.add_argument("--round-gap", type=float, default=7.0, help="pause between concurrent rounds, seconds")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--expect-backend-down", action="store_true")
    parser.add_argument("--force", action="store_true", help="init-keys: overwrite an existing keys.json")
    args = parser.parse_args()

    if args.stage == "init-keys":
        return stage_init_keys(args, None)
    if args.stage == "all":
        stages = ["backend", "core", "budget", "context", "load", "concurrent", "queue", "ratelimit", "report"]
    else:
        stages = [args.stage]
    failed = False
    for name in stages:
        print(f"\n=== {name} ===")
        if name == "report":
            failed = failed or stage_report(args, Recorder(name, args.gateway_url, args.backend_url)) != 0
            continue
        recorder = Recorder(name, args.gateway_url, args.backend_url)
        code = STAGES[name](args, recorder)
        expectations_ok = recorder.write()
        failed = failed or code != 0 or not expectations_ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
