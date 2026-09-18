"""SQLite state, optimistic versions and audit trail for Day 15."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from task_lifecycle import required


@dataclass(frozen=True)
class TaskState:
    task_id: str
    objective: str
    state: str
    paused: bool
    pause_reason: str | None
    version: int
    artifacts: dict[str, str]

    def to_dict(self) -> dict:
        return asdict(self)


class TaskStore:
    def __init__(self, directory: str | Path):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "task_lifecycle.db"
        self._lock = threading.RLock()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, objective TEXT NOT NULL, "
                "state TEXT NOT NULL, paused INTEGER NOT NULL, pause_reason TEXT, version INTEGER NOT NULL, "
                "artifacts_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, "
                "event TEXT NOT NULL, from_state TEXT, to_state TEXT, action TEXT, allowed INTEGER NOT NULL, "
                "code TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )

    def create(self, task_id: str, objective: str, initial_state: str) -> TaskState:
        state = TaskState(required("task_id", task_id, 80), required("objective", objective), initial_state, False, None, 1, {})
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            try:
                connection.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)", self._values(state))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Задача {state.task_id!r} уже существует") from exc
            self._event(connection, state.task_id, "created", None, state.state, None, True, "created", state.objective)
        return state

    def get(self, task_id: str) -> TaskState:
        task_id = required("task_id", task_id, 80)
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT task_id, objective, state, paused, pause_reason, version, artifacts_json FROM tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Задача {task_id!r} не найдена")
        return TaskState(row[0], row[1], row[2], bool(row[3]), row[4], row[5], json.loads(row[6]))

    def save(self, state: TaskState, previous_version: int, *, event: str, from_state: str,
             action: str | None, code: str, details: str) -> TaskState:
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            cursor = connection.execute(
                "UPDATE tasks SET objective=?, state=?, paused=?, pause_reason=?, version=?, artifacts_json=? "
                "WHERE task_id=? AND version=?",
                (*self._values(state)[1:], state.task_id, previous_version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Состояние уже изменилось; загрузите актуальную версию")
            self._event(connection, state.task_id, event, from_state, state.state, action, True, code, details)
        return state

    def reject(self, task_id: str, *, state: str, action: str, code: str, details: str):
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            self._event(connection, task_id, "transition_rejected", state, state, action, False, code, details)

    def history(self, task_id: str) -> list[dict]:
        self.get(task_id)
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT event,from_state,to_state,action,allowed,code,details,created_at FROM events "
                "WHERE task_id=? ORDER BY id", (task_id,),
            ).fetchall()
        keys = ("event", "from_state", "to_state", "action", "allowed", "code", "details", "created_at")
        return [{**dict(zip(keys, row)), "allowed": bool(row[4])} for row in rows]

    @staticmethod
    def _values(state: TaskState) -> tuple:
        return (state.task_id, state.objective, state.state, int(state.paused), state.pause_reason,
                state.version, json.dumps(state.artifacts, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _event(connection, task_id, event, from_state, to_state, action, allowed, code, details):
        connection.execute(
            "INSERT INTO events (task_id,event,from_state,to_state,action,allowed,code,details) VALUES (?,?,?,?,?,?,?,?)",
            (task_id, event, from_state, to_state, action, int(allowed), code, details),
        )
