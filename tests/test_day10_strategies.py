import importlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DAY10_DIR = ROOT / "day10-context-strategies"


@pytest.fixture()
def day10_modules():
    previous_path = list(sys.path)
    names = ("agent", "providers", "history_store", "token_metrics", "strategies")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(DAY10_DIR))
    try:
        yield {
            name: importlib.import_module(name)
            for name in ("agent", "history_store", "strategies")
        }
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path[:] = previous_path


class FakeProvider:
    """Отвечает по-разному на основной запрос и на вызов извлекателя фактов."""

    id = "fake"
    label = "Fake"
    default_model = "fake-model"

    def __init__(self, agent_module, facts_payload=None):
        self.agent = agent_module
        self.facts_payload = facts_payload or {"цель": "собрать ТЗ"}
        self.answer_calls = []
        self.facts_calls = []

    def available(self):
        return True

    def model_options(self):
        return [self.default_model]

    def prepare_prompt(self, messages, _config):
        return "\n".join(f"{item.role}: {item.content}" for item in messages)

    def generate(self, messages, config, _cancel_event):
        usage = self.agent.TokenUsage(20, 5, 25, True)
        if config.system_prompt == self.agent.FACTS_SYSTEM_PROMPT:
            self.facts_calls.append(tuple(messages))
            payload = self.facts_payload
            if callable(payload):
                payload = payload(messages)
            return self.agent.ProviderReply(
                json.dumps(payload, ensure_ascii=False),
                self.id,
                self.default_model,
                usage,
            )
        self.answer_calls.append(tuple(messages))
        return self.agent.ProviderReply("Принято.", self.id, self.default_model, usage)


def test_sliding_window_drops_everything_beyond_n(day10_modules):
    agent_mod = day10_modules["agent"]
    provider = FakeProvider(agent_mod)
    config = agent_mod.AgentConfig(strategy="sliding", recent_messages=4)
    agent = agent_mod.ChatAgent([provider], config=config)

    for index in range(5):
        agent.ask(f"Сообщение {index}")

    assert provider.facts_calls == [], "sliding не должен звать извлекатель фактов"
    last = provider.answer_calls[-1]
    assert len(last) == 5  # четыре дословных + текущая реплика
    assert all(item.role != "system" for item in last)
    assert last[0].content == "Сообщение 2"  # более ранние просто отброшены
    assert len(agent.history) == 10  # полный transcript остаётся в агенте


def test_facts_survive_falling_out_of_the_window(day10_modules, tmp_path):
    agent_mod = day10_modules["agent"]
    store_mod = day10_modules["history_store"]
    store = store_mod.SQLiteHistoryStore(tmp_path / "day10.db")
    provider = FakeProvider(
        agent_mod,
        facts_payload=lambda messages: (
            {"бюджет": "480000"} if "480" in messages[0].content else {}
        ),
    )
    config = agent_mod.AgentConfig(strategy="facts", recent_messages=2)
    agent = agent_mod.ChatAgent(
        [provider], config=config, history_store=store, session_id="s-facts"
    )

    agent.ask("Бюджет проекта — 480000 рублей.")
    for index in range(3):
        agent.ask(f"Нейтральный ход {index}")
    reply = agent.ask("Какой бюджет?")

    assert len(provider.facts_calls) == 5  # по одному вызову на реплику пользователя
    last = provider.answer_calls[-1]
    assert last[0].role == "system" and "бюджет: 480000" in last[0].content
    assert len(last) == 4  # facts + два дословных + текущая реплика
    # Сообщение с бюджетом давно вышло из окна, но факт в запросе остался.
    assert all("480000" not in item.content for item in last[1:])
    assert reply.context["facts"] == {"бюджет": "480000"}
    assert reply.session_usage.known_calls == 10  # 5 ответов + 5 вызовов памяти

    restored = agent_mod.ChatAgent(
        [FakeProvider(agent_mod)], config=config, history_store=store, session_id="s-facts"
    )
    assert restored.facts.values == {"бюджет": "480000"}
    assert restored.facts.revision == 1


def test_branches_diverge_from_one_checkpoint(day10_modules, tmp_path):
    agent_mod = day10_modules["agent"]
    store_mod = day10_modules["history_store"]
    store = store_mod.SQLiteHistoryStore(tmp_path / "day10.db")
    provider = FakeProvider(agent_mod)
    config = agent_mod.AgentConfig(strategy="branching")
    agent = agent_mod.ChatAgent(
        [provider], config=config, history_store=store, session_id="s-branch"
    )

    agent.ask("Общая часть ТЗ")
    checkpoint = agent.checkpoint()
    assert checkpoint == 2

    agent.create_branch("mobile", label="Мобильное приложение")
    agent.ask("Вариант A: мобильное приложение")
    assert [m.content for m in agent.history][0] == "Общая часть ТЗ"
    assert len(agent.history) == 4

    agent.switch_branch("main")
    assert len(agent.history) == 2, "main не видит сообщений ветки"

    agent.create_branch("web", fork_index=checkpoint, label="Веб")
    agent.ask("Вариант B: веб-сервис")
    web_history = [m.content for m in agent.history]
    assert web_history[0] == "Общая часть ТЗ"
    assert "Вариант A: мобильное приложение" not in web_history

    agent.switch_branch("mobile")
    assert "Вариант A: мобильное приложение" in [m.content for m in agent.history]
    assert "Вариант B: веб-сервис" not in [m.content for m in agent.history]

    # branching отдаёт ветку целиком, а не окно.
    last = provider.answer_calls[-1]
    assert len(last) == 3 and last[0].content == "Общая часть ТЗ"

    names = {row["branch_id"] for row in agent.branches()}
    assert names == {"main", "mobile", "web"}
    with pytest.raises(store_mod.BranchError):
        agent.create_branch("web")


def test_unknown_strategy_is_rejected(day10_modules):
    agent_mod = day10_modules["agent"]
    with pytest.raises(ValueError):
        agent_mod.AgentConfig(strategy="magic")
