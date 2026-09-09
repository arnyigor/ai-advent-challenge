"""Persistent Day 8 chat history and token measurement log."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class SQLiteHistoryStore:
    """Stores messages and per-request token metrics in one SQLite file."""

    def __init__(self, path: str | Path):
        self._path = str(path)
        self._lock = threading.Lock()
        with self._connect() as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "session_id TEXT NOT NULL, "
                "turn_id TEXT, "
                "role TEXT NOT NULL, "
                "content TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS request_log ("
                "request_id TEXT PRIMARY KEY, "
                "session_id TEXT NOT NULL, "
                "turn_index INTEGER NOT NULL, "
                "provider TEXT, "
                "model TEXT, "
                "status TEXT NOT NULL, "
                "metrics_json TEXT NOT NULL, "
                "usage_json TEXT NOT NULL, "
                "attempts_json TEXT NOT NULL, "
                "error TEXT, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )

    def _connect(self) -> contextlib.closing[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    def load(self, session_id: str, limit: int | None = None) -> list[tuple[str, str]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY rowid",
                (session_id,),
            ).fetchall()
        items = [(str(row["role"]), str(row["content"])) for row in rows]
        if limit is not None and len(items) > limit:
            items = items[-limit:]
        return items

    def append(self, session_id: str, role: str, content: str) -> None:
        with self._lock, self._connect() as conn, conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )

    def next_turn_index(self, session_id: str) -> int:
        with self._lock, self._connect() as conn:
            value = conn.execute(
                "SELECT COALESCE(MAX(turn_index), 0) + 1 FROM request_log "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
        return int(value)

    def append_exchange_with_log(
        self,
        *,
        session_id: str,
        request_id: str,
        turn_index: int,
        user_text: str,
        assistant_text: str,
        provider: str,
        model: str,
        status: str,
        metrics: dict,
        usage: dict,
        attempts: list[dict],
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn, conn:
            conn.execute(
                "INSERT INTO messages (session_id, turn_id, role, content) "
                "VALUES (?, ?, ?, ?)",
                (session_id, request_id, "user", user_text),
            )
            conn.execute(
                "INSERT INTO messages (session_id, turn_id, role, content) "
                "VALUES (?, ?, ?, ?)",
                (session_id, request_id, "assistant", assistant_text),
            )
            self._insert_log(
                conn,
                request_id=request_id,
                session_id=session_id,
                turn_index=turn_index,
                provider=provider,
                model=model,
                status=status,
                metrics=metrics,
                usage=usage,
                attempts=attempts,
                error=error,
            )

    def append_log(
        self,
        *,
        request_id: str,
        session_id: str,
        turn_index: int,
        provider: str | None,
        model: str | None,
        status: str,
        metrics: dict,
        usage: dict,
        attempts: list[dict],
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn, conn:
            self._insert_log(
                conn,
                request_id=request_id,
                session_id=session_id,
                turn_index=turn_index,
                provider=provider,
                model=model,
                status=status,
                metrics=metrics,
                usage=usage,
                attempts=attempts,
                error=error,
            )

    def _insert_log(
        self,
        conn: sqlite3.Connection,
        *,
        request_id: str,
        session_id: str,
        turn_index: int,
        provider: str | None,
        model: str | None,
        status: str,
        metrics: dict,
        usage: dict,
        attempts: list[dict],
        error: str | None,
    ) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO request_log ("
            "request_id, session_id, turn_index, provider, model, status, "
            "metrics_json, usage_json, attempts_json, error"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_id,
                session_id,
                turn_index,
                provider,
                model,
                status,
                json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                json.dumps(usage, ensure_ascii=False, sort_keys=True),
                json.dumps(attempts, ensure_ascii=False, sort_keys=True),
                error,
            ),
        )

    def load_request_logs(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM request_log WHERE session_id = ? ORDER BY turn_index, created_at",
                (session_id,),
            ).fetchall()
        return [self._row_to_log(row) for row in rows]

    def clear(self, session_id: str) -> None:
        with self._lock, self._connect() as conn, conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM request_log WHERE session_id = ?", (session_id,))

    @staticmethod
    def _loads(value: str, fallback: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback

    def _row_to_log(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "request_id": row["request_id"],
            "session_id": row["session_id"],
            "turn_index": row["turn_index"],
            "provider": row["provider"],
            "model": row["model"],
            "status": row["status"],
            "metrics": self._loads(row["metrics_json"], {}),
            "usage": self._loads(row["usage_json"], {}),
            "attempts": self._loads(row["attempts_json"], []),
            "error": row["error"],
            "created_at": row["created_at"],
        }


def _demo() -> None:
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        store = SQLiteHistoryStore(path)
        store.append_exchange_with_log(
            session_id="s1",
            request_id="r1",
            turn_index=1,
            user_text="hi",
            assistant_text="hello",
            provider="fake",
            model="fake-model",
            status="ok",
            metrics={"request_tokens_before_send": {"value": 3}},
            usage={"total_tokens": 5, "reported": True},
            attempts=[{"provider": "fake", "status": "ok"}],
        )
        assert store.load("s1") == [("user", "hi"), ("assistant", "hello")]
        assert store.next_turn_index("s1") == 2
        assert store.load_request_logs("s1")[0]["usage"]["total_tokens"] == 5
        store.clear("s1")
        assert store.load("s1") == []
        print("history_store self-check OK")
    finally:
        os.remove(path)


if __name__ == "__main__":
    _demo()
