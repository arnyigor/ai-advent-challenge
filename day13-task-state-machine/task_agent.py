"""Agent facade that restores task context from the state machine."""

from __future__ import annotations

from task_state import TaskState, TaskStateMachine


class TaskAgent:
    def __init__(self, machine: TaskStateMachine):
        self.machine = machine

    def start(self, task_id: str, objective: str) -> dict:
        state = self.machine.create(task_id, objective)
        return self._response(state, "Задача создана. Подготовьте план и подтвердите его.")

    def status(self, task_id: str) -> dict:
        state = self.machine.store.get(task_id)
        return self._response(state, "Состояние восстановлено из хранилища.")

    def act(self, task_id: str, action: str, result: str) -> dict:
        state = self.machine.apply(task_id, action, result=result)
        messages = {
            "execution": "План сохранён. Можно выполнять задачу.",
            "validation": "Результат сохранён. Требуется проверка.",
            "done": "Проверка принята. Задача завершена.",
        }
        return self._response(state, messages[state.stage])

    def pause(self, task_id: str, reason: str) -> dict:
        return self._response(self.machine.pause(task_id, reason), "Задача поставлена на паузу; весь контекст сохранён.")

    def resume(self, task_id: str) -> dict:
        state = self.machine.resume(task_id)
        return self._response(state, "Продолжаю с сохранённого шага; повторять описание задачи не нужно.")

    def _response(self, state: TaskState, message: str) -> dict:
        return {
            "message": message,
            "state": state.to_dict(),
            "history": self.machine.store.history(state.task_id),
        }
