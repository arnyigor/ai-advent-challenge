import importlib
import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DAY08_DIR = ROOT / "day08-token-usage"


@pytest.fixture()
def day8_modules():
    previous_path = list(sys.path)
    saved = {
        name: sys.modules.pop(name)
        for name in ("agent", "providers", "history_store", "token_metrics", "web_server")
        if name in sys.modules
    }
    sys.path.insert(0, str(DAY08_DIR))
    try:
        modules = {
            name: importlib.import_module(name)
            for name in ("agent", "history_store", "token_metrics")
        }
        yield modules
    finally:
        for name in ("agent", "providers", "history_store", "token_metrics", "web_server"):
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path[:] = previous_path


class FakeProvider:
    id = "fake"
    label = "Fake"
    default_model = "fake-model"

    def __init__(self, agent_module, outcomes=None):
        self._agent = agent_module
        self._outcomes = list(outcomes or ["ok"])
        self.calls = []

    def available(self):
        return True

    def model_options(self):
        return [self.default_model]

    def prepare_prompt(self, messages, _config):
        return "\n".join(f"{m.role}: {m.content}" for m in messages)

    def generate(self, messages, config, cancel_event):
        self.calls.append((tuple(messages), config, cancel_event))
        outcome = self._outcomes[min(len(self.calls) - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return self._agent.ProviderReply(
            str(outcome),
            self.id,
            self.default_model,
            self._agent.TokenUsage(11, 7, 18, True),
        )


def test_successful_turn_persists_messages_and_token_log(day8_modules, tmp_path):
    agent_mod = day8_modules["agent"]
    store_mod = day8_modules["history_store"]
    store = store_mod.SQLiteHistoryStore(tmp_path / "day8.db")
    provider = FakeProvider(agent_mod, ["Ответ"])

    agent = agent_mod.ChatAgent([provider], history_store=store, session_id="s")
    reply = agent.ask("Привет")

    assert reply.turn_index == 1
    assert reply.usage == agent_mod.TokenUsage(11, 7, 18, True)
    assert reply.session_usage.total_tokens == 18
    assert reply.token_metrics["current_message_tokens"]["is_estimate"] is True
    assert store.load("s") == [("user", "Привет"), ("assistant", "Ответ")]
    logs = store.load_request_logs("s")
    assert len(logs) == 1
    assert logs[0]["status"] == "ok"
    assert logs[0]["metrics"]["request_tokens_before_send"]["value"] > 0

    restored = agent_mod.ChatAgent(
        [FakeProvider(agent_mod)], history_store=store, session_id="s"
    )
    assert len(restored.history) == 2
    assert restored.session_usage.total_tokens == 18


def test_day8_does_not_trim_history_before_provider_call(day8_modules):
    agent_mod = day8_modules["agent"]
    provider = FakeProvider(agent_mod, ["A1", "A2"])
    config = agent_mod.AgentConfig(context_chars=1_000, max_input_chars=10_000)
    agent = agent_mod.ChatAgent([provider], config=config)

    agent.ask("Q" * 2_000)
    agent.ask("next")

    sent = provider.calls[1][0]
    assert sent == (
        agent_mod.Message("user", "Q" * 2_000),
        agent_mod.Message("assistant", "A1"),
        agent_mod.Message("user", "next"),
    )


def test_local_context_limit_is_logged_without_provider_call(day8_modules, tmp_path):
    agent_mod = day8_modules["agent"]
    store_mod = day8_modules["history_store"]

    class DeepSeekSizedProvider(FakeProvider):
        id = "deepseek"
        label = "DeepSeek"
        default_model = "deepseek-v4-flash"

        def generate(self, *_args, **_kwargs):
            pytest.fail("Provider must not be called after local budget failure")

    store = store_mod.SQLiteHistoryStore(tmp_path / "day8.db")
    provider = DeepSeekSizedProvider(agent_mod)
    config = agent_mod.AgentConfig(max_output_tokens=1_000_000, max_input_chars=100_000)
    agent = agent_mod.ChatAgent([provider], config=config, history_store=store, session_id="s")

    with pytest.raises(agent_mod.AgentContextLimitError) as caught:
        agent.ask("!" * 60_000)

    assert caught.value.token_metrics["context_budget"]["status"] == "local_context_limit"
    assert agent.history == ()
    logs = store.load_request_logs("s")
    assert logs[0]["status"] == "local_context_limit"
    assert logs[0]["usage"]["reported"] is False
