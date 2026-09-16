import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DAY = ROOT / "day13-task-state-machine"


@pytest.fixture
def modules():
    names = ("task_state", "task_agent", "model_comparison", "web_server")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(DAY))
    try:
        state = importlib.import_module("task_state")
        agent = importlib.import_module("task_agent")
        yield state, agent
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path.remove(str(DAY))


def configured(tmp_path, modules):
    state, agent = modules
    store = state.TaskStateStore(tmp_path)
    return agent.TaskAgent(state.TaskStateMachine(store)), store


def test_full_state_machine_and_artifacts(tmp_path, modules):
    agent, _ = configured(tmp_path, modules)
    created = agent.start("report", "Сделать экспорт PDF")
    assert created["state"]["stage"] == "planning"
    assert created["state"]["expected_action"] == "approve_plan"
    execution = agent.act("report", "approve_plan", "План из трёх шагов")
    validation = agent.act("report", "complete_execution", "Экспорт реализован")
    done = agent.act("report", "approve_validation", "PDF открыт и проверен")
    assert done["state"]["stage"] == "done"
    assert done["state"]["expected_action"] is None
    assert done["state"]["artifacts"] == {
        "planning": "План из трёх шагов",
        "execution": "Экспорт реализован",
        "validation": "PDF открыт и проверен",
    }


@pytest.mark.parametrize("stage,actions", [
    ("planning", []),
    ("execution", [("approve_plan", "План")]),
    ("validation", [("approve_plan", "План"), ("complete_execution", "Код")]),
])
def test_pause_and_resume_at_every_active_stage(tmp_path, modules, stage, actions):
    agent, _ = configured(tmp_path, modules)
    agent.start("task", "Цель, которую не нужно повторять")
    for action, result in actions:
        agent.act("task", action, result)
    paused = agent.pause("task", f"Пауза на {stage}")
    assert paused["state"]["stage"] == stage and paused["state"]["paused"] is True
    resumed = agent.resume("task")
    assert resumed["state"]["stage"] == stage
    assert resumed["state"]["objective"] == "Цель, которую не нужно повторять"
    assert resumed["state"]["paused"] is False


def test_new_agent_process_restores_without_explanation(tmp_path, modules):
    first, _ = configured(tmp_path, modules)
    first.start("persistent", "Исходное объяснение задачи")
    first.act("persistent", "approve_plan", "Сохранённый план")
    first.pause("persistent", "Перезапуск")
    second, _ = configured(tmp_path, modules)
    resumed = second.resume("persistent")
    assert resumed["state"]["objective"] == "Исходное объяснение задачи"
    assert resumed["state"]["artifacts"]["planning"] == "Сохранённый план"
    assert resumed["state"]["expected_action"] == "complete_execution"


def test_invalid_transitions_are_rejected(tmp_path, modules):
    agent, _ = configured(tmp_path, modules)
    agent.start("strict", "Проверить переходы")
    with pytest.raises(ValueError, match="Ожидается действие"):
        agent.act("strict", "approve_validation", "Попытка перескочить")
    agent.pause("strict", "Стоп")
    with pytest.raises(ValueError, match="на паузе"):
        agent.act("strict", "approve_plan", "План")


def test_comparison_uses_same_prompt_and_does_not_mutate_state(tmp_path, modules, monkeypatch):
    agent, store = configured(tmp_path, modules)
    agent.start("compare", "Сравнить модели")
    comparison = importlib.import_module("model_comparison")
    prompts = []

    def fake_result(model_id, label, provider, model, prompt):
        prompts.append(prompt)
        return comparison.ModelResult(model_id, label, provider, model, f"ответ-{model_id}", 10)

    monkeypatch.setattr(comparison.ModelComparator, "_deepseek", staticmethod(
        lambda prompt: fake_result("deepseek", "DeepSeek", "deepseek", "flash", prompt)
    ))
    monkeypatch.setattr(comparison.ModelComparator, "_wormsoft", staticmethod(
        lambda prompt: fake_result("wormsoft", "GPT-OSS", "wormsoft", "20b", prompt)
    ))
    before = store.get("compare")
    result = comparison.ModelComparator().compare(before)
    after = store.get("compare")
    assert len(result["results"]) == 2
    assert prompts[0] == prompts[1]
    assert before == after
    assert "Текущий этап: planning" in result["prompt"]
