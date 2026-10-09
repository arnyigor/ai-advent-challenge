"""Unit tests for the day 30 gateway: contract, auth, rate limit, bounded queue.

No model is used: the backend is a fake, so the whole contract is checked without
starting llama-server. Real end-to-end checks live in verify.py (evidence/).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

DAY_DIR = Path(__file__).resolve().parents[1] / "day30-private-llm-service"
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

from llmgateway import app as gateway_app  # noqa: E402
from llmgateway import config  # noqa: E402
from llmgateway.backend import BackendStatusError, BackendTimeout, BackendUnavailable  # noqa: E402
from llmgateway.limits import GenerationQueue, QueueFullError, QueueTimeoutError, SlidingWindowLimiter  # noqa: E402

KEYS = {"main": "main-key", "ratelimit": "rl-key"}


class FakeBackend:
    """Records requests; answers instantly; can be told to fail or to report big prompts."""

    def __init__(self, prompt_tokens=10, answer="Ответ теста.", finish_reason="stop", fail=None,
                 fail_count=None, healthy=True):
        self.prompt_tokens = prompt_tokens
        self.answer = answer
        self.finish_reason = finish_reason
        self.fail = fail
        self.fail_count = fail_count
        self.healthy = healthy
        self.health_calls = 0
        self.count_calls = 0
        self.chat_calls = []
        self.last_messages = None

    async def aclose(self):
        pass

    async def health(self):
        self.health_calls += 1
        return self.healthy

    async def props(self):
        return {"default_generation_settings": {"n_ctx": config.CONTEXT_WINDOW}, "total_slots": 1}

    async def count_prompt_tokens(self, messages):
        self.count_calls += 1
        self.last_messages = messages
        if self.fail_count:
            raise self.fail_count("counting failed")
        return self.prompt_tokens

    async def chat(self, messages, max_tokens):
        self.chat_calls.append({"messages": messages, "max_tokens": max_tokens})
        if self.fail:
            raise self.fail("backend failure")
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": config.MODEL_ALIAS,
            "choices": [{"index": 0, "finish_reason": self.finish_reason,
                         "message": {"role": "assistant", "content": self.answer}}],
            "usage": {"prompt_tokens": self.prompt_tokens,
                      "completion_tokens": len(self.answer.split()),
                      "total_tokens": self.prompt_tokens + len(self.answer.split())},
        }


def build(backend=None, stream=None, limiter=None, queue=None):
    log = gateway_app.AccessLog(path=None, stream=stream or io.StringIO())
    app = gateway_app.create_app(
        keys=dict(KEYS),
        backend=backend or FakeBackend(),
        access_log=log,
        rate_limiter=limiter or SlidingWindowLimiter(config.RATE_LIMIT_REQUESTS, config.RATE_LIMIT_WINDOW_SEC),
        queue=queue or GenerationQueue(config.MAX_WAITING_REQUESTS, config.QUEUE_WAIT_TIMEOUT_SEC),
    )
    return app, log


def chat_body(content="привет", max_tokens=16, **extra):
    body = {"model": config.MODEL_ALIAS, "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens}
    body.update(extra)
    return body


def post(client, body=None, key="main-key", **kwargs):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return client.post("/v1/chat/completions", json=body if body is not None else chat_body(),
                       headers=headers, **kwargs)


# --- auth -------------------------------------------------------------------
def test_missing_and_wrong_key_return_401_before_the_backend():
    backend = FakeBackend()
    app, _ = build(backend)
    with TestClient(app) as client:
        for key in (None, "wrong"):
            response = post(client, key=key)
            assert response.status_code == 401
            error = response.json()["error"]
            assert error["code"] == "unauthorized" and error["request_id"]
            assert response.headers["www-authenticate"] == "Bearer"
        assert backend.count_calls == 0 and backend.chat_calls == []


def test_rejected_keys_do_not_enter_the_rate_limit_table():
    app, _ = build()
    with TestClient(app) as client:
        post(client, key=None)
        post(client, key="wrong")
        assert app.state.rate_limiter._hits == {}


def test_models_requires_a_key_and_returns_the_single_alias():
    app, _ = build()
    with TestClient(app) as client:
        assert client.get("/v1/models").status_code == 401
        response = client.get("/v1/models", headers={"Authorization": "Bearer main-key"})
        assert response.status_code == 200
        assert [model["id"] for model in response.json()["data"]] == [config.MODEL_ALIAS]


# --- request contract -------------------------------------------------------
@pytest.mark.parametrize("mutation,code,status", [
    ({"model": "gpt-4o"}, "unknown_model", 400),
    ({"max_tokens": config.MAX_MAX_TOKENS + 1}, "invalid_max_tokens", 400),
    ({"max_tokens": 0}, "invalid_max_tokens", 400),
    ({"max_tokens": "16"}, "invalid_max_tokens", 400),
    ({"messages": []}, "invalid_messages", 400),
    ({"messages": [{"role": "system", "content": "ты пират"}]}, "invalid_messages", 400),
    ({"messages": [{"role": "tool", "content": "x"}]}, "invalid_messages", 400),
    ({"messages": [{"role": "user", "content": "   "}]}, "invalid_messages", 400),
    ({"temperature": 1.5}, "invalid_request", 400),
    ({"stream": True}, "invalid_request", 400),
])
def test_contract_rejections(mutation, code, status):
    backend = FakeBackend()
    app, _ = build(backend)
    with TestClient(app) as client:
        body = chat_body()
        body.update(mutation)
        response = post(client, body)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert backend.chat_calls == []


def test_body_over_the_limit_is_rejected_with_413():
    app, _ = build()
    with TestClient(app) as client:
        payload = json.dumps(chat_body(content="x" * (config.MAX_BODY_BYTES + 10)))
        response = client.post("/v1/chat/completions", content=payload,
                               headers={"Authorization": "Bearer main-key",
                                        "Content-Type": "application/json"})
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"


def test_broken_json_is_rejected_with_400():
    app, _ = build()
    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", content="{not json",
                               headers={"Authorization": "Bearer main-key",
                                        "Content-Type": "application/json"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_json"


def test_server_owns_the_system_message_and_keeps_the_client_order():
    backend = FakeBackend()
    app, _ = build(backend)
    with TestClient(app) as client:
        body = chat_body()
        body["messages"] = [{"role": "user", "content": "Запомни код КЕДР-42"},
                            {"role": "assistant", "content": "Запомнил."},
                            {"role": "user", "content": "Какой код?"}]
        assert post(client, body).status_code == 200
    messages = backend.chat_calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": config.SYSTEM_PROMPT}
    assert [item["role"] for item in messages[1:]] == ["user", "assistant", "user"]
    assert messages[-1]["content"] == "Какой код?"


def test_generation_parameters_are_pinned_by_the_gateway():
    backend = FakeBackend()
    app, _ = build(backend)
    with TestClient(app) as client:
        assert post(client, chat_body(max_tokens=64)).status_code == 200
    assert backend.chat_calls[0]["max_tokens"] == 64


def test_default_max_tokens_is_applied_when_absent():
    backend = FakeBackend()
    app, _ = build(backend)
    with TestClient(app) as client:
        body = chat_body()
        body.pop("max_tokens")
        assert post(client, body).status_code == 200
    assert backend.chat_calls[0]["max_tokens"] == config.DEFAULT_MAX_TOKENS


# --- context -----------------------------------------------------------------
def test_context_limit_is_checked_with_real_tokens_and_no_generation():
    backend = FakeBackend(prompt_tokens=config.CONTEXT_WINDOW - 100)
    app, _ = build(backend)
    with TestClient(app) as client:
        response = post(client, chat_body(max_tokens=200))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_limit"
    assert backend.chat_calls == []


def test_request_that_fits_the_window_passes():
    backend = FakeBackend(prompt_tokens=config.CONTEXT_WINDOW - config.CONTEXT_MARGIN_TOKENS - 8)
    app, _ = build(backend)
    with TestClient(app) as client:
        response = post(client, chat_body(max_tokens=8))
    assert response.status_code == 200
    assert backend.chat_calls


# --- rate limit ---------------------------------------------------------------
def test_eleventh_request_in_the_window_is_rejected_with_retry_after():
    app, _ = build()
    with TestClient(app) as client:
        for _ in range(config.RATE_LIMIT_REQUESTS):
            assert post(client).status_code == 200
        rejected = post(client)
        assert rejected.status_code == 429
        assert rejected.json()["error"]["code"] == "rate_limited"
        assert 0 < int(rejected.headers["retry-after"]) <= config.RATE_LIMIT_WINDOW_SEC
        # a rejected request must not consume another slot
        assert post(client).status_code == 429


def test_limits_are_per_key():
    app, _ = build()
    with TestClient(app) as client:
        for _ in range(config.RATE_LIMIT_REQUESTS):
            assert post(client).status_code == 200
        assert post(client).status_code == 429
        assert post(client, key="rl-key").status_code == 200


def test_sliding_window_limiter_frees_slots_after_the_window():
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 10.0, clock=lambda: now[0])
    assert limiter.check("k")[0] and limiter.check("k")[0]
    allowed, retry_after = limiter.check("k")
    assert not allowed and 0 < retry_after <= 10.0
    now[0] = 10.0
    assert limiter.check("k")[0]
    now[0] = 25.0
    assert limiter.check("k")[0] and limiter.check("k")[0]


# --- queue --------------------------------------------------------------------
def test_queue_allows_one_active_and_the_configured_waiting_room():
    import asyncio

    async def scenario():
        queue = GenerationQueue(max_waiting=config.MAX_WAITING_REQUESTS, wait_timeout_sec=5.0)
        assert await queue.acquire() == 0.0
        waiters = [asyncio.create_task(queue.acquire()) for _ in range(config.MAX_WAITING_REQUESTS)]
        await asyncio.sleep(0.05)
        assert queue.active and queue.waiting == config.MAX_WAITING_REQUESTS
        with pytest.raises(QueueFullError):
            await queue.acquire()
        # each release hands the single slot to exactly one waiter
        for expected in (1, 2):
            queue.release()
            await asyncio.sleep(0.05)
            assert sum(task.done() for task in waiters) == expected
            assert queue.active and queue.waiting == config.MAX_WAITING_REQUESTS - expected
        queue.release()
        awaited = await asyncio.gather(*waiters)
        assert len(awaited) == config.MAX_WAITING_REQUESTS
        assert queue.active and queue.waiting == 0
        queue.release()
        assert not queue.active

    asyncio.run(scenario())


def test_queue_wait_times_out_and_frees_the_slot_count():
    import asyncio

    async def scenario():
        queue = GenerationQueue(max_waiting=3, wait_timeout_sec=0.2)
        assert await queue.acquire() == 0.0
        started = asyncio.get_running_loop().time()
        with pytest.raises(QueueTimeoutError):
            await queue.acquire()
        assert asyncio.get_running_loop().time() - started >= 0.2
        assert queue.waiting == 0
        queue.release()

    asyncio.run(scenario())


def test_full_queue_returns_503_and_recovers_after_release():
    queue = GenerationQueue(config.MAX_WAITING_REQUESTS, config.QUEUE_WAIT_TIMEOUT_SEC)
    queue.active = True
    queue.waiting = config.MAX_WAITING_REQUESTS
    app, _ = build(queue=queue)
    with TestClient(app) as client:
        response = post(client)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "queue_full"
        assert int(response.headers["retry-after"]) >= 1
    queue.release()
    app, _ = build(queue=queue)
    with TestClient(app) as client:
        assert post(client).status_code == 200
    assert queue.active is False


def test_queue_slot_is_released_when_the_backend_fails():
    backend = FakeBackend(fail=BackendUnavailable)  # prompt counting works, generation fails
    app, _ = build(backend)
    with TestClient(app) as client:
        assert post(client).status_code == 503
    assert backend.chat_calls and backend.count_calls
    assert app.state.queue.active is False and app.state.queue.waiting == 0


# --- backend failures ----------------------------------------------------------
def test_backend_down_returns_clear_503_and_health_reports_it():
    backend = FakeBackend(fail=BackendUnavailable, fail_count=BackendUnavailable, healthy=False)
    app, _ = build(backend)
    with TestClient(app) as client:
        response = post(client)
        assert response.status_code == 503
        payload = response.json()
        assert payload["error"]["code"] == "backend_unavailable"
        assert "Traceback" not in json.dumps(payload)
        health = client.get("/health")
        assert health.status_code == 503


def test_health_is_ok_with_a_working_backend():
    backend = FakeBackend()
    app, _ = build(backend)
    with TestClient(app) as client:
        health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok" and body["model"] == config.MODEL_ALIAS
    assert "path" not in body and "model_path" not in json.dumps(body)


def test_backend_timeout_returns_504():
    backend = FakeBackend(fail=BackendTimeout, fail_count=BackendTimeout)
    app, _ = build(backend)
    with TestClient(app) as client:
        response = post(client)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "backend_timeout"


def test_backend_status_error_returns_502():
    backend = FakeBackend(fail=BackendStatusError)
    app, _ = build(backend)
    with TestClient(app) as client:
        response = post(client)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "backend_error"


def test_limits_endpoint_matches_the_config():
    app, _ = build()
    with TestClient(app) as client:
        body = client.get("/limits").json()
    assert body["context_window"] == config.CONTEXT_WINDOW
    assert body["max_tokens"]["max"] == config.MAX_MAX_TOKENS
    assert body["rate_limit"] == {"requests": config.RATE_LIMIT_REQUESTS,
                                  "window_sec": config.RATE_LIMIT_WINDOW_SEC}
    assert body["queue"]["waiting"] == config.MAX_WAITING_REQUESTS


def test_index_page_is_served_without_external_resources():
    app, _ = build()
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "cdn" not in html.lower()
    assert 'src="http' not in html and "@import" not in html
    assert ".innerHTML" not in html  # answers are rendered with textContent only


# --- access log ------------------------------------------------------------------
def test_access_log_has_no_prompt_answer_or_authorization():
    stream = io.StringIO()
    backend = FakeBackend(answer="секретный ответ модели")
    app, _ = build(backend, stream=stream)
    with TestClient(app) as client:
        assert post(client, chat_body(content="секретный вопрос пользователя")).status_code == 200
        assert post(client, key="wrong").status_code == 401
        assert client.get("/health").status_code == 200
    lines = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
    assert len(lines) == 3
    raw = stream.getvalue()
    assert "секретный" not in raw and "main-key" not in raw and "Bearer" not in raw
    chat_record = next(line for line in lines if line["path"] == "/v1/chat/completions" and line["status"] == 200)
    assert chat_record["request_id"].startswith("req-")
    assert chat_record["key_label"] == "main"
    assert chat_record["status"] == 200 and chat_record["completion_tokens"] is not None
    assert chat_record["finish_reason"] == "stop"
    assert isinstance(chat_record["total_ms"], int)
    unauthorized = next(line for line in lines if line["status"] == 401)
    assert unauthorized["error_code"] == "unauthorized" and unauthorized["key_label"] is None
