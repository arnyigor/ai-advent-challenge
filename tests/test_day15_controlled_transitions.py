import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DAY = ROOT / "day15-controlled-transitions"


@pytest.fixture
def modules():
    names = ("task_lifecycle", "task_store", "lifecycle_assistant", "model_comparison", "web_server")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(DAY))
    try:
        yield tuple(importlib.import_module(name) for name in names[:4])
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path.remove(str(DAY))


def configured(tmp_path, modules):
    lifecycle, store, assistant, _ = modules
    contract = lifecycle.LifecycleContract.load(DAY / "lifecycle.json")
    storage = store.TaskStore(tmp_path)
    return assistant.LifecycleAssistant(contract, storage), contract, storage


def test_contract_has_no_terminal_outgoing_transition(modules):
    lifecycle, *_ = modules
    contract = lifecycle.LifecycleContract.load(DAY / "lifecycle.json")
    assert contract.initial_state == "planning"
    assert contract.terminal_states == {"completed"}
    assert contract.allowed_actions("completed") == ()
    assert contract.transitions["validation"]["approve_validation"].target == "completed"


def test_full_controlled_lifecycle(tmp_path, modules):
    agent, _, _ = configured(tmp_path, modules)
    created = agent.start("pdf", "Добавить экспорт PDF")
    review = agent.transition("pdf", "submit_plan", "План из трёх шагов", created["state"]["version"])
    implementation = agent.transition("pdf", "approve_plan", "План утверждён", review["state"]["version"])
    validation = agent.transition("pdf", "submit_result", "Экспорт реализован", implementation["state"]["version"])
    done = agent.transition("pdf", "approve_validation", "PDF и тесты проверены", validation["state"]["version"])
    assert done["state"]["state"] == "completed"
    assert done["state"]["artifacts"] == {
        "plan": "План из трёх шагов", "plan_approval": "План утверждён",
        "implementation": "Экспорт реализован", "validation_report": "PDF и тесты проверены",
    }


@pytest.mark.parametrize("action", ["approve_plan", "submit_result", "approve_validation"])
def test_cannot_jump_from_planning(tmp_path, modules, action):
    agent, _, _ = configured(tmp_path, modules)
    before = agent.start("strict", "Проверить запреты")["state"]
    result = agent.transition("strict", action, "Попытка перепрыгнуть", before["version"])
    assert result["allowed"] is False
    assert result["code"] == "invalid_transition"
    assert result["state"] == before
    assert result["history"][-1]["allowed"] is False


def test_rejection_loops_preserve_feedback(tmp_path, modules):
    agent, _, _ = configured(tmp_path, modules)
    agent.start("loops", "Проверить возвраты")
    review = agent.transition("loops", "submit_plan", "Черновой план")
    planning = agent.transition("loops", "reject_plan", "Добавить критерии", review["state"]["version"])
    assert planning["state"]["state"] == "planning"
    assert planning["state"]["artifacts"]["plan_rejection"] == "Добавить критерии"
    agent.transition("loops", "submit_plan", "Исправленный план")
    agent.transition("loops", "approve_plan", "Утверждено")
    validation = agent.transition("loops", "submit_result", "Первая реализация")
    implementation = agent.transition("loops", "fail_validation", "Найден дефект", validation["state"]["version"])
    assert implementation["state"]["state"] == "implementation"
    assert implementation["state"]["artifacts"]["validation_failure"] == "Найден дефект"


@pytest.mark.parametrize("state_name,actions", [
    ("planning", []),
    ("plan_review", [("submit_plan", "План")]),
    ("implementation", [("submit_plan", "План"), ("approve_plan", "Да")]),
    ("validation", [("submit_plan", "План"), ("approve_plan", "Да"), ("submit_result", "Код")]),
])
def test_pause_resume_at_every_active_state(tmp_path, modules, state_name, actions):
    agent, _, _ = configured(tmp_path, modules)
    agent.start("pause", "Цель сохраняется")
    for action, result in actions:
        agent.transition("pause", action, result)
    paused = agent.pause("pause", "Перезапуск")
    assert paused["state"]["state"] == state_name and paused["state"]["paused"] is True
    blocked = agent.transition("pause", paused["allowed_actions"][0], "Нельзя")
    assert blocked["code"] == "paused" and blocked["state_changed"] is False
    resumed = agent.resume("pause")
    assert resumed["state"]["state"] == state_name
    assert resumed["state"]["objective"] == "Цель сохраняется"


def test_new_assistant_restores_by_id(tmp_path, modules):
    first, contract, storage = configured(tmp_path, modules)
    first.start("restore", "Исходная цель")
    first.transition("restore", "submit_plan", "Сохранённый план")
    first.transition("restore", "approve_plan", "Согласовано")
    first.pause("restore", "Закрытие приложения")
    assistant_module = modules[2]
    second = assistant_module.LifecycleAssistant(contract, type(storage)(tmp_path))
    restored = second.resume("restore")
    assert restored["state"]["state"] == "implementation"
    assert restored["state"]["artifacts"]["plan"] == "Сохранённый план"


def test_stale_version_is_logged_and_does_not_mutate(tmp_path, modules):
    agent, _, _ = configured(tmp_path, modules)
    created = agent.start("version", "Контроль версии")
    rejected = agent.transition("version", "submit_plan", "План", created["state"]["version"] + 1)
    assert rejected["code"] == "version_conflict"
    assert rejected["state"]["version"] == created["state"]["version"]


def test_model_comparison_uses_same_snapshot_and_does_not_mutate(tmp_path, modules, monkeypatch):
    agent, contract, storage = configured(tmp_path, modules)
    state = storage.get(agent.start("models", "Сравнить модели")["state"]["task_id"])
    comparison = modules[3]
    prompts = []

    def fake(model_id, label, provider, model):
        def call(prompt):
            prompts.append(prompt)
            return comparison.ModelResult(model_id, label, provider, model, "ok", "submit_plan", 5)
        return call

    monkeypatch.setattr(comparison.ModelComparator, "_deepseek", staticmethod(fake("deepseek", "DeepSeek", "DeepSeek", "flash")))
    monkeypatch.setattr(comparison.ModelComparator, "_routerai", staticmethod(fake("routerai", "Qwen", "RouterAI", "27b")))
    before = storage.get("models")
    result = comparison.ModelComparator(contract).compare(state, "Сразу завершить?")
    after = storage.get("models")
    assert prompts[0] == prompts[1]
    assert result["state_changed"] is False
    assert before == after

