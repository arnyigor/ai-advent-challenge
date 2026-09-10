import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DAY09_DIR = ROOT / "day09-context-compression"


@pytest.fixture()
def day9_modules():
    previous_path = list(sys.path)
    names = ("agent", "providers", "history_store", "token_metrics", "context_manager")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(DAY09_DIR))
    try:
        yield {
            name: importlib.import_module(name)
            for name in ("agent", "history_store", "context_manager")
        }
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path[:] = previous_path


class FakeProvider:
    id = "fake"
    label = "Fake"
    default_model = "fake-model"

    def __init__(self, agent_module):
        self.agent = agent_module
        self.answer_calls = []
        self.summary_calls = []

    def available(self):
        return True

    def model_options(self):
        return [self.default_model]

    def prepare_prompt(self, messages, _config):
        return "\n".join(f"{item.role}: {item.content}" for item in messages)

    def generate(self, messages, config, _cancel_event):
        usage = self.agent.TokenUsage(20, 5, 25, True)
        if config.system_prompt == self.agent.SUMMARY_SYSTEM_PROMPT:
            self.summary_calls.append(tuple(messages))
            return self.agent.ProviderReply(
                "Код проекта — Маяк-17; пользователь проверяет память.",
                self.id,
                self.default_model,
                usage,
            )
        self.answer_calls.append(tuple(messages))
        return self.agent.ProviderReply(
            "Принято.", self.id, self.default_model, usage
        )


def test_context_manager_compresses_only_full_batches(day9_modules):
    context = day9_modules["context_manager"]
    history = [object() for _ in range(20)]
    manager = context.ContextManager(
        context.CompressionConfig(enabled=True, recent_messages=6, batch_size=10)
    )

    assert len(manager.ready_batch(history)) == 10
    manager.advance("Первая сводка", 10)
    assert manager.ready_batch(history) == ()
    assert manager.state.summarized_message_count == 10


def test_agent_keeps_full_transcript_but_sends_summary_and_tail(day9_modules, tmp_path):
    agent_mod = day9_modules["agent"]
    store_mod = day9_modules["history_store"]
    store = store_mod.SQLiteHistoryStore(tmp_path / "day9.db")
    provider = FakeProvider(agent_mod)
    config = agent_mod.AgentConfig(
        recent_messages=4,
        summary_batch_size=4,
        max_input_chars=10_000,
    )
    agent = agent_mod.ChatAgent(
        [provider], config=config, history_store=store, session_id="compressed"
    )

    messages = [
        "Запомни: код проекта — Маяк-17. " + "важная деталь " * 30,
        "Фоновый вопрос 1. " + "нейтральный контекст " * 30,
        "Фоновый вопрос 2",
        "Фоновый вопрос 3",
        "Какой код проекта?",
    ]
    replies = [agent.ask(message) for message in messages]

    assert len(provider.summary_calls) == 1
    assert len(provider.answer_calls) == 5
    last_request = provider.answer_calls[-1]
    assert last_request[0].role == "system"
    assert "Маяк-17" in last_request[0].content
    assert len(last_request) == 6  # summary + four verbatim messages + current user
    assert len(store.load("compressed")) == 10  # complete source transcript is retained
    assert store.load_summary("compressed")["summarized_message_count"] == 4
    assert replies[-1].compression["estimated_tokens_saved_this_request"] > 0
    assert replies[-1].session_usage.known_calls == 6  # five answers + one summary

    restored = agent_mod.ChatAgent(
        [FakeProvider(agent_mod)],
        config=config,
        history_store=store,
        session_id="compressed",
    )
    assert len(restored.history) == 10
    assert restored.summary.revision == 1
    assert restored.session_usage.known_calls == 6


def test_control_mode_sends_full_history_without_summary(day9_modules):
    agent_mod = day9_modules["agent"]
    provider = FakeProvider(agent_mod)
    config = agent_mod.AgentConfig(
        compression_enabled=False,
        recent_messages=2,
        summary_batch_size=2,
        max_input_chars=10_000,
    )
    agent = agent_mod.ChatAgent([provider], config=config)

    for index in range(4):
        agent.ask(f"Сообщение {index}")

    assert provider.summary_calls == []
    assert len(provider.answer_calls[-1]) == 7
    assert provider.answer_calls[-1][0].content == "Сообщение 0"
    assert agent.summary.content == ""
