"""Assistant facade: models may suggest, only the guard may transition."""

from __future__ import annotations

from task_lifecycle import LifecycleContract, TransitionGuard, TransitionRejected, required
from task_store import TaskState, TaskStore


class LifecycleAssistant:
    def __init__(self, contract: LifecycleContract, store: TaskStore):
        self.contract = contract
        self.store = store
        self.guard = TransitionGuard(contract)

    def start(self, task_id: str, objective: str) -> dict:
        return self._response(self.store.create(task_id, objective, self.contract.initial_state),
                              "Задача создана. Сначала представьте план.")

    def status(self, task_id: str) -> dict:
        return self._response(self.store.get(task_id), "Состояние восстановлено по task_id.")

    def transition(self, task_id: str, action: str, result: str, expected_version: int | None = None) -> dict:
        state = self.store.get(task_id)
        action = required("action", action, 80)
        try:
            if expected_version is not None and expected_version != state.version:
                raise TransitionRejected("version_conflict", "Версия устарела; загрузите актуальное состояние",
                                         self.contract.allowed_actions(state.state))
            rule = self.guard.check(state=state.state, action=action, paused=state.paused)
            result = required("result", result)
        except TransitionRejected as exc:
            self.store.reject(task_id, state=state.state, action=action, code=exc.code, details=str(exc))
            return self._response(state, str(exc), allowed=False, code=exc.code,
                                  override_actions=exc.allowed_actions)
        artifacts = dict(state.artifacts)
        artifacts[rule.artifact] = result
        updated = TaskState(state.task_id, state.objective, rule.target, False, None,
                            state.version + 1, artifacts)
        updated = self.store.save(updated, state.version, event="transition", from_state=state.state,
                                  action=action, code="transition_applied", details=result)
        return self._response(updated, f"Переход {state.state} → {rule.target} выполнен.")

    def pause(self, task_id: str, reason: str) -> dict:
        state = self.store.get(task_id)
        if state.state in self.contract.terminal_states:
            raise ValueError("Завершённую задачу нельзя поставить на паузу")
        if state.paused:
            raise ValueError("Задача уже на паузе")
        reason = required("reason", reason, 500)
        updated = TaskState(**{**state.to_dict(), "paused": True, "pause_reason": reason,
                               "version": state.version + 1})
        self.store.save(updated, state.version, event="paused", from_state=state.state,
                        action="pause", code="paused", details=reason)
        return self._response(updated, "Задача поставлена на паузу; этап и артефакты сохранены.")

    def resume(self, task_id: str) -> dict:
        state = self.store.get(task_id)
        if not state.paused:
            raise ValueError("Задача не находится на паузе")
        updated = TaskState(**{**state.to_dict(), "paused": False, "pause_reason": None,
                               "version": state.version + 1})
        self.store.save(updated, state.version, event="resumed", from_state=state.state,
                        action="resume", code="resumed", details="")
        return self._response(updated, "Продолжаю с сохранённого этапа; повторять задачу не нужно.")

    def _response(self, state: TaskState, message: str, *, allowed: bool = True,
                  code: str = "ok", override_actions=None) -> dict:
        actions = tuple(override_actions) if override_actions is not None else self.contract.allowed_actions(state.state)
        return {"allowed": allowed, "code": code, "message": message, "state_changed": allowed,
                "allowed_actions": list(actions), "state": state.to_dict(),
                "history": self.store.history(state.task_id)}
