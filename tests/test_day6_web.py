import json
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


DAY06_DIR = Path(__file__).resolve().parents[1] / "day06-first-agent"
if str(DAY06_DIR) not in sys.path:
    sys.path.insert(0, str(DAY06_DIR))

from agent import (
    AgentStore,
    ChatAgent,
    Message,
    ProviderCancelledError,
    ProviderReply,
    TokenUsage,
)
from web_server import create_server


class FakeProvider:
    id = "fake"
    label = "Fake"
    default_model = "fake-model"

    def __init__(self):
        self.calls = []

    def available(self):
        return True

    def generate(self, messages, config, cancel_event):
        self.calls.append((tuple(messages), config))
        call_number = len(self.calls)
        usage = TokenUsage(
            call_number,
            call_number + 1,
            call_number * 2 + 1,
            True,
            call_number - 1,
        )
        return ProviderReply(
            text=f"Ответ {call_number}",
            provider=self.id,
            model=self.default_model,
            usage=usage,
        )


@pytest.fixture
def web_api():
    providers = []

    def agent_factory():
        provider = FakeProvider()
        providers.append(provider)
        return ChatAgent([provider])

    server = create_server("127.0.0.1", 0, AgentStore(agent_factory))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", providers
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def request_json(base_url, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_config_returns_only_safe_public_shape(web_api):
    base_url, _providers = web_api

    status, payload = request_json(base_url, "/api/config")

    assert status == 200
    assert set(payload) == {"agent", "providers", "config"}
    assert payload["agent"] == "ChatAgent"
    assert set(payload["config"]) == {
        "temperature",
        "max_output_tokens",
        "max_history_messages",
        "max_input_chars",
        "max_output_chars",
        "thinking_level",
        "thinking_levels",
        "input_policy",
        "output_policy",
        "judge_enabled",
        "system_prompt_configured",
    }
    assert payload["config"]["judge_enabled"] is False
    assert all(
        set(provider) == {"id", "label", "model", "available"}
        for provider in payload["providers"]
    )


def test_chat_serializes_nested_usage_and_accumulates_session(web_api):
    base_url, providers = web_api

    first_status, first = request_json(
        base_url, "/api/chat", {"session_id": "same", "message": "Первый"}
    )
    second_status, second = request_json(
        base_url, "/api/chat", {"session_id": "same", "message": "Второй"}
    )

    assert (first_status, second_status) == (200, 200)
    assert first["reply"]["usage"] == {
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
        "reported": True,
        "reasoning_tokens": 0,
    }
    assert first["reply"]["session_usage"] == first["reply"]["usage"]
    assert second["reply"]["usage"]["total_tokens"] == 5
    assert second["reply"]["session_usage"] == {
        "input_tokens": 3,
        "output_tokens": 5,
        "total_tokens": 8,
        "reported": True,
        "reasoning_tokens": 1,
    }
    assert second["reply"]["judgement"] is None
    assert providers[0].calls[1][0] == (
        Message("user", "Первый"),
        Message("assistant", "Ответ 1"),
        Message("user", "Второй"),
    )


def test_chat_honors_thinking_level_override(web_api):
    base_url, providers = web_api

    status, payload = request_json(
        base_url,
        "/api/chat",
        {"session_id": "s", "message": "Вопрос", "thinking_level": "high"},
    )

    assert status == 200
    assert providers[0].calls[0][1].thinking_level == "high"
    assert payload["reply"]["text"] == "Ответ 1"


def test_chat_selects_explicit_provider_and_skips_others():
    providers_seen = []

    def agent_factory():
        first = FakeProvider()
        first.id = "one"
        second = FakeProvider()
        second.id = "two"
        providers_seen.extend([first, second])
        return ChatAgent([first, second])

    server = create_server("127.0.0.1", 0, AgentStore(agent_factory))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        status, payload = request_json(
            base_url,
            "/api/chat",
            {"session_id": "s", "message": "Вопрос", "provider": "two"},
        )
        assert status == 200
        assert payload["reply"]["provider"] == "two"
        assert providers_seen[0].calls == []
        assert len(providers_seen[1].calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_chat_rejects_unknown_provider_with_400(web_api):
    base_url, providers = web_api

    status, payload = request_json(
        base_url,
        "/api/chat",
        {"session_id": "s", "message": "Вопрос", "provider": "nope"},
    )

    assert status == 400
    assert "nope" in payload["error"]
    assert providers[0].calls == []


def test_reset_clears_history_and_session_usage(web_api):
    base_url, providers = web_api
    request_json(base_url, "/api/chat", {"session_id": "reset-me", "message": "До"})

    reset_status, reset_payload = request_json(
        base_url, "/api/reset", {"session_id": "reset-me"}
    )
    after_status, after = request_json(
        base_url, "/api/chat", {"session_id": "reset-me", "message": "После"}
    )

    assert reset_status == 200
    assert reset_payload == {"ok": True}
    assert after_status == 200
    assert after["reply"]["session_usage"] == after["reply"]["usage"]
    assert providers[0].calls[1][0] == (Message("user", "После"),)


@pytest.mark.parametrize("invalid_message", ["   ", [], 42])
def test_invalid_input_returns_400_without_calling_provider(web_api, invalid_message):
    base_url, providers = web_api

    status, payload = request_json(
        base_url,
        "/api/chat",
        {"session_id": "invalid", "message": invalid_message},
    )

    assert status == 400
    assert set(payload) == {"error"}
    assert providers[0].calls == []


def test_cancel_endpoint_stops_active_request_without_committing_state():
    call_started = threading.Event()

    class SlowProvider(FakeProvider):
        def generate(self, messages, config, cancel_event):
            self.calls.append((tuple(messages), config))
            call_started.set()
            if not cancel_event.wait(2):
                return ProviderReply(
                    "late",
                    self.id,
                    self.default_model,
                    TokenUsage(10, 10, 20, True, 4),
                )
            raise ProviderCancelledError("cancelled")

    provider = SlowProvider()
    server = create_server(
        "127.0.0.1",
        0,
        AgentStore(lambda: ChatAgent([provider])),
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    chat_result = {}

    def post_chat():
        chat_result["response"] = request_json(
            base_url,
            "/api/chat",
            {"session_id": "cancel-me", "message": "Долгий вопрос"},
        )

    chat_thread = threading.Thread(target=post_chat)
    chat_thread.start()
    try:
        assert call_started.wait(1)
        cancel_status, cancel_payload = request_json(
            base_url, "/api/cancel", {"session_id": "cancel-me"}
        )
        chat_thread.join(3)

        assert cancel_status == 200
        assert cancel_payload == {"ok": True}
        assert not chat_thread.is_alive()
        status, payload = chat_result["response"]
        assert status == 409
        assert payload == {"error": "Запрос отменён", "cancelled": True}
        agent = server.agent_store.get("cancel-me")
        assert agent.history == ()
        assert agent.session_usage == TokenUsage()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
