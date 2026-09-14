"""Three physically separate SQLite memory layers with explicit fact routing."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path

LAYERS = ("short", "working", "long")


@contextmanager
def _connection(path: Path):
    # sqlite3.Connection's context manager commits, but does not close the file.
    # Closing explicitly matters on Windows (and for temporary evaluation DBs).
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            yield conn


def _required(label: str, value: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label}: нужна непустая строка не длиннее {maximum} символов")
    return value.strip()


class MemoryStore:
    """Short: user+session; working: user+task; long: user.

    Chat turns are written only to short-term memory after a successful answer.
    Facts enter any layer only through save_fact(layer=...).
    """

    def __init__(self, directory: str | Path):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.paths = {layer: root / f"{layer}.db" for layer in LAYERS}
        self._lock = threading.RLock()
        for layer, path in self.paths.items():
            with _connection(path) as conn:
                if layer == "short":
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS messages ("
                        "user_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                        "role TEXT NOT NULL, content TEXT NOT NULL, "
                        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                    )
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS facts ("
                        "user_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                        "key TEXT NOT NULL, value TEXT NOT NULL, "
                        "PRIMARY KEY (user_id, session_id, key))"
                    )
                elif layer == "working":
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS facts ("
                        "user_id TEXT NOT NULL, task_id TEXT NOT NULL, "
                        "key TEXT NOT NULL, value TEXT NOT NULL, "
                        "PRIMARY KEY (user_id, task_id, key))"
                    )
                else:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS facts ("
                        "user_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
                        "PRIMARY KEY (user_id, key))"
                    )

    def save_fact(
        self, layer: str, *, user_id: str, session_id: str, task_id: str,
        key: str, value: str,
    ) -> None:
        if layer not in LAYERS:
            raise ValueError(f"Неизвестный слой: {layer}")
        user_id = _required("user_id", user_id, 80)
        key = _required("key", key, 80)
        value = _required("value", value, 1000)
        scope = self._scope(layer, session_id, task_id)
        columns = {"short": "user_id, session_id", "working": "user_id, task_id", "long": "user_id"}[layer]
        placeholders = ", ".join("?" for _ in range(len(scope) + 3))
        with self._lock, _connection(self.paths[layer]) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO facts ({columns}, key, value) VALUES ({placeholders})",
                (user_id, *scope, key, value),
            )

    @staticmethod
    def _scope(layer: str, session_id: str, task_id: str) -> tuple[str, ...]:
        if layer == "short":
            return (_required("session_id", session_id, 80),)
        if layer == "working":
            return (_required("task_id", task_id, 80),)
        return ()

    def facts(self, layer: str, *, user_id: str, session_id: str, task_id: str) -> dict[str, str]:
        if layer not in LAYERS:
            raise ValueError(f"Неизвестный слой: {layer}")
        user_id = _required("user_id", user_id, 80)
        scope = self._scope(layer, session_id, task_id)
        where = {"short": "user_id = ? AND session_id = ?", "working": "user_id = ? AND task_id = ?", "long": "user_id = ?"}[layer]
        with self._lock, _connection(self.paths[layer]) as conn:
            rows = conn.execute(
                f"SELECT key, value FROM facts WHERE {where} ORDER BY key", (user_id, *scope)
            ).fetchall()
        return dict(rows)

    def messages(self, *, user_id: str, session_id: str, limit: int | None = None) -> list[dict[str, str]]:
        user_id = _required("user_id", user_id, 80)
        session_id = _required("session_id", session_id, 80)
        with self._lock, _connection(self.paths["short"]) as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE user_id = ? AND session_id = ? ORDER BY rowid",
                (user_id, session_id),
            ).fetchall()
        if limit is not None:
            rows = rows[-limit:]
        return [{"role": role, "content": content} for role, content in rows]

    def append_turn(self, *, user_id: str, session_id: str, user_text: str, answer: str) -> None:
        user_id = _required("user_id", user_id, 80)
        session_id = _required("session_id", session_id, 80)
        _required("user_text", user_text, 8000)
        _required("answer", answer, 32000)
        with self._lock, _connection(self.paths["short"]) as conn:
            conn.executemany(
                "INSERT INTO messages (user_id, session_id, role, content) VALUES (?, ?, ?, ?)",
                [(user_id, session_id, "user", user_text), (user_id, session_id, "assistant", answer)],
            )

    def snapshot(self, *, user_id: str, session_id: str, task_id: str) -> dict:
        return {
            "short": {
                "facts": self.facts("short", user_id=user_id, session_id=session_id, task_id=task_id),
                "messages": self.messages(user_id=user_id, session_id=session_id),
            },
            "working": self.facts("working", user_id=user_id, session_id=session_id, task_id=task_id),
            "long": self.facts("long", user_id=user_id, session_id=session_id, task_id=task_id),
        }
