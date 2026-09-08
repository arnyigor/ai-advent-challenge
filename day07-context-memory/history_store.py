"""Персистентная история диалога поверх SQLite (stdlib), по session_id."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path


class SQLiteHistoryStore:
    """Хранит сообщения всех сессий в одном .db файле.

    ponytail: один процессный лок на все операции — для локального
    однопользовательского чата этого достаточно; при реальной конкурентной
    нагрузке заменить на sqlite WAL + отдельные соединения per-thread.
    """

    def __init__(self, path: str | Path):
        self._path = str(path)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL)"
            )

    def _connect(self) -> contextlib.closing[sqlite3.Connection]:
        return contextlib.closing(sqlite3.connect(self._path))

    def load(self, session_id: str, limit: int | None = None) -> list[tuple[str, str]]:
        with self._lock, self._connect() as conn, conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY rowid",
                (session_id,),
            ).fetchall()
        if limit is not None and len(rows) > limit:
            rows = rows[-limit:]
        return rows

    def append(self, session_id: str, role: str, content: str) -> None:
        with self._lock, self._connect() as conn, conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )

    def clear(self, session_id: str) -> None:
        with self._lock, self._connect() as conn, conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))


def _demo() -> None:
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        store = SQLiteHistoryStore(path)
        store.append("s1", "user", "hi")
        store.append("s1", "assistant", "hello")
        assert store.load("s1") == [("user", "hi"), ("assistant", "hello")]
        assert store.load("s1", limit=1) == [("assistant", "hello")]
        assert store.load("s2") == []

        reopened = SQLiteHistoryStore(path)
        assert reopened.load("s1") == [("user", "hi"), ("assistant", "hello")]

        reopened.clear("s1")
        assert reopened.load("s1") == []
        print("history_store self-check OK")
    finally:
        os.remove(path)


if __name__ == "__main__":
    _demo()
