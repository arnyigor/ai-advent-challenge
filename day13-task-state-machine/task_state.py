"""Persistent task state machine for Day 13."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

STAGES = ("planning", "execution", "validation", "done")
EXPECTED_ACTIONS = {
    "planning": "approve_plan",
    "execution": "complete_execution",
    "validation": "approve_validation",
    "done": None,
}
NEXT_STAGE = {"planning": "execution", "execution": "validation", "validation": "done"}


def _required(label: str, value: str, maximum: int = 8000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label}: нужна непустая строка не длиннее {maximum} символов")
    return value.strip()


@dataclass(frozen=True)
class TaskState:
    task_id: str
    objective: str
    stage: str
    current_step: str
    expected_action: str | None
    paused: bool
    pause_reason: str | None
    version: int
    artifacts: dict[str, str]

    def to_dict(self) -> dict:
        return asdict(self)


class TaskStateStore:
    """SQLite persistence with optimistic version checks and an audit trail."""

    def __init__(self, directory: str | Path):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "task_states.db"
        self._lock = threading.RLock()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "task_id TEXT PRIMARY KEY, objective TEXT NOT NULL, stage TEXT NOT NULL, "
                "current_step TEXT NOT NULL, expected_action TEXT, paused INTEGER NOT NULL, "
                "pause_reason TEXT, version INTEGER NOT NULL, artifacts_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS task_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, event TEXT NOT NULL, "
                "from_stage TEXT, to_stage TEXT, details TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )

    def create(self, task_id: str, objective: str) -> TaskState:
        task_id = _required("task_id", task_id, 80)
        objective = _required("objective", objective)
        state = TaskState(task_id, objective, "planning", "Составить и согласовать план", "approve_plan", False, None, 1, {})
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            try:
                connection.execute(
                    "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._values(state),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Задача {task_id!r} уже существует") from exc
            self._event(connection, task_id, "created", None, "planning", objective)
        return state

    def get(self, task_id: str) -> TaskState:
        task_id = _required("task_id", task_id, 80)
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT task_id, objective, stage, current_step, expected_action, paused, "
                "pause_reason, version, artifacts_json FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Задача {task_id!r} не найдена")
        return TaskState(*row[:5], bool(row[5]), row[6], row[7], json.loads(row[8]))

    def save(self, state: TaskState, *, previous_version: int, event: str, from_stage: str, details: str = "") -> TaskState:
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            cursor = connection.execute(
                "UPDATE tasks SET objective=?, stage=?, current_step=?, expected_action=?, paused=?, "
                "pause_reason=?, version=?, artifacts_json=? WHERE task_id=? AND version=?",
                (*self._values(state)[1:], state.task_id, previous_version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Состояние задачи уже изменилось; перечитайте его")
            self._event(connection, state.task_id, event, from_stage, state.stage, details)
        return state

    def history(self, task_id: str) -> list[dict]:
        self.get(task_id)
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT event, from_stage, to_stage, details, created_at FROM task_events "
                "WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        keys = ("event", "from_stage", "to_stage", "details", "created_at")
        return [dict(zip(keys, row)) for row in rows]

    @staticmethod
    def _values(state: TaskState) -> tuple:
        return (
            state.task_id, state.objective, state.stage, state.current_step,
            state.expected_action, int(state.paused), state.pause_reason, state.version,
            json.dumps(state.artifacts, ensure_ascii=False, sort_keys=True),
        )

    @staticmethod
    def _event(connection, task_id: str, event: str, from_stage: str | None, to_stage: str, details: str):
        connection.execute(
            "INSERT INTO task_events (task_id, event, from_stage, to_stage, details) VALUES (?, ?, ?, ?, ?)",
            (task_id, event, from_stage, to_stage, details),
        )


class TaskStateMachine:
    STEPS = {
        "planning": "Составить и согласовать план",
        "execution": "Выполнить согласованный план",
        "validation": "Проверить результат по критериям",
        "done": "Задача завершена",
    }

    def __init__(self, store: TaskStateStore):
        self.store = store

    def create(self, task_id: str, objective: str) -> TaskState:
        return self.store.create(task_id, objective)

    def apply(self, task_id: str, action: str, *, result: str = "") -> TaskState:
        state = self.store.get(task_id)
        if state.paused:
            raise ValueError("Задача на паузе; сначала выполните resume")
        if state.stage == "done":
            raise ValueError("Задача уже завершена")
        if action != state.expected_action:
            raise ValueError(f"Ожидается действие {state.expected_action!r}, получено {action!r}")
        result = _required("result", result)
        next_stage = NEXT_STAGE[state.stage]
        artifacts = {**state.artifacts, state.stage: result}
        updated = TaskState(
            state.task_id, state.objective, next_stage, self.STEPS[next_stage],
            EXPECTED_ACTIONS[next_stage], False, None, state.version + 1, artifacts,
        )
        return self.store.save(updated, previous_version=state.version, event="transition", from_stage=state.stage, details=action)

    def pause(self, task_id: str, reason: str) -> TaskState:
        state = self.store.get(task_id)
        if state.stage == "done":
            raise ValueError("Завершённую задачу нельзя поставить на паузу")
        if state.paused:
            raise ValueError("Задача уже на паузе")
        reason = _required("reason", reason, 500)
        updated = TaskState(**{**state.to_dict(), "paused": True, "pause_reason": reason, "version": state.version + 1})
        return self.store.save(updated, previous_version=state.version, event="paused", from_stage=state.stage, details=reason)

    def resume(self, task_id: str) -> TaskState:
        state = self.store.get(task_id)
        if not state.paused:
            raise ValueError("Задача не находится на паузе")
        updated = TaskState(**{**state.to_dict(), "paused": False, "pause_reason": None, "version": state.version + 1})
        return self.store.save(updated, previous_version=state.version, event="resumed", from_stage=state.stage, details="")
