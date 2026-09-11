"""Persistent Day 10 transcript with dialogue branches and key-value facts.

Отличия от Day 10 предшественника (Day 9, rolling summary):

* у каждого сообщения есть ``branch_id``;
* ветка знает родителя и ``fork_index`` — сколько родительских сообщений она
  унаследовала, поэтому история ветки восстанавливается без копирования;
* вместо одной сводки на сессию хранится key-value память на каждую ветку.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


MAIN_BRANCH = "main"


class BranchError(ValueError):
    """Ветка не найдена или уже существует."""


class SQLiteHistoryStore:
    """Messages, per-request token metrics, branches and facts in one file."""

    def __init__(self, path: str | Path):
        self._path = str(path)
        self._lock = threading.Lock()
        with self._connect() as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "session_id TEXT NOT NULL, "
                "branch_id TEXT NOT NULL DEFAULT 'main', "
                "turn_id TEXT, "
                "role TEXT NOT NULL, "
                "content TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS request_log ("
                "request_id TEXT PRIMARY KEY, "
                "session_id TEXT NOT NULL, "
                "branch_id TEXT NOT NULL DEFAULT 'main', "
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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS branches ("
                "session_id TEXT NOT NULL, "
                "branch_id TEXT NOT NULL, "
                "parent_branch_id TEXT, "
                "fork_index INTEGER NOT NULL DEFAULT 0, "
                "label TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY (session_id, branch_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS facts ("
                "session_id TEXT NOT NULL, "
                "branch_id TEXT NOT NULL DEFAULT 'main', "
                "key TEXT NOT NULL, "
                "value TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY (session_id, branch_id, key))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS facts_meta ("
                "session_id TEXT NOT NULL, "
                "branch_id TEXT NOT NULL, "
                "revision INTEGER NOT NULL DEFAULT 0, "
                "usage_json TEXT NOT NULL DEFAULT '{}', "
                "PRIMARY KEY (session_id, branch_id))"
            )

    def _connect(self) -> contextlib.closing[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    # ---------------------------------------------------------------- branches

    def _ensure_branch(self, conn: sqlite3.Connection, session_id: str, branch_id: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO branches (session_id, branch_id, parent_branch_id, "
            "fork_index, label) VALUES (?, ?, NULL, 0, ?)",
            (session_id, branch_id, "основная" if branch_id == MAIN_BRANCH else branch_id),
        )

    def _branch_row(self, conn: sqlite3.Connection, session_id: str, branch_id: str):
        return conn.execute(
            "SELECT * FROM branches WHERE session_id = ? AND branch_id = ?",
            (session_id, branch_id),
        ).fetchone()

    def _own_messages(
        self, conn: sqlite3.Connection, session_id: str, branch_id: str
    ) -> list[tuple[str, str]]:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? AND branch_id = ? "
            "ORDER BY rowid",
            (session_id, branch_id),
        ).fetchall()
        return [(str(row["role"]), str(row["content"])) for row in rows]

    def _resolve_history(
        self, conn: sqlite3.Connection, session_id: str, branch_id: str
    ) -> list[tuple[str, str]]:
        """Идёт вверх по родителям и склеивает унаследованные префиксы."""
        chain: list[sqlite3.Row] = []
        seen: set[str] = set()
        current = branch_id
        while current and current not in seen:
            seen.add(current)
            row = self._branch_row(conn, session_id, current)
            if row is None:
                break
            chain.append(row)
            current = row["parent_branch_id"]

        history: list[tuple[str, str]] = []
        for row in reversed(chain):
            if row["parent_branch_id"]:
                history = history[: int(row["fork_index"])]
            history = history + self._own_messages(conn, session_id, str(row["branch_id"]))
        if not chain:
            history = self._own_messages(conn, session_id, branch_id)
        return history

    def load(
        self, session_id: str, limit: int | None = None, branch_id: str = MAIN_BRANCH
    ) -> list[tuple[str, str]]:
        with self._lock, self._connect() as conn:
            items = self._resolve_history(conn, session_id, branch_id)
        if limit is not None and len(items) > limit:
            items = items[-limit:]
        return items

    def list_branches(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM branches WHERE session_id = ? ORDER BY created_at, branch_id",
                (session_id,),
            ).fetchall()
            return [
                {
                    "branch_id": str(row["branch_id"]),
                    "parent_branch_id": row["parent_branch_id"],
                    "fork_index": int(row["fork_index"]),
                    "label": str(row["label"]),
                    "created_at": row["created_at"],
                    "message_count": len(
                        self._resolve_history(conn, session_id, str(row["branch_id"]))
                    ),
                }
                for row in rows
            ]

    def create_branch(
        self,
        session_id: str,
        *,
        branch_id: str,
        parent_branch_id: str,
        fork_index: int,
        label: str = "",
    ) -> dict[str, Any]:
        """Форк родителя на первых ``fork_index`` сообщениях (checkpoint)."""
        branch_id = str(branch_id).strip()
        if not branch_id:
            raise BranchError("Имя ветки не может быть пустым")
        if isinstance(fork_index, bool) or not isinstance(fork_index, int) or fork_index < 0:
            raise BranchError("fork_index должен быть неотрицательным целым")
        with self._lock, self._connect() as conn, conn:
            self._ensure_branch(conn, session_id, parent_branch_id)
            if self._branch_row(conn, session_id, branch_id) is not None:
                raise BranchError(f"Ветка уже существует: {branch_id}")
            parent_length = len(self._resolve_history(conn, session_id, parent_branch_id))
            if fork_index > parent_length:
                raise BranchError(
                    f"Checkpoint {fork_index} за пределами ветки {parent_branch_id} "
                    f"({parent_length} сообщений)"
                )
            conn.execute(
                "INSERT INTO branches (session_id, branch_id, parent_branch_id, "
                "fork_index, label) VALUES (?, ?, ?, ?, ?)",
                (session_id, branch_id, parent_branch_id, fork_index, label or branch_id),
            )
            # Факты наследуются от родителя: ветка продолжает тот же диалог.
            conn.execute(
                "INSERT OR REPLACE INTO facts (session_id, branch_id, key, value) "
                "SELECT session_id, ?, key, value FROM facts "
                "WHERE session_id = ? AND branch_id = ?",
                (branch_id, session_id, parent_branch_id),
            )
            conn.execute(
                "INSERT OR REPLACE INTO facts_meta (session_id, branch_id, revision, usage_json) "
                "SELECT session_id, ?, revision, usage_json FROM facts_meta "
                "WHERE session_id = ? AND branch_id = ?",
                (branch_id, session_id, parent_branch_id),
            )
        return {
            "branch_id": branch_id,
            "parent_branch_id": parent_branch_id,
            "fork_index": fork_index,
            "label": label or branch_id,
        }

    def branch_exists(self, session_id: str, branch_id: str) -> bool:
        with self._lock, self._connect() as conn:
            return self._branch_row(conn, session_id, branch_id) is not None

    # ------------------------------------------------------------------ facts

    def load_facts(self, session_id: str, branch_id: str = MAIN_BRANCH) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM facts WHERE session_id = ? AND branch_id = ? "
                "ORDER BY rowid",
                (session_id, branch_id),
            ).fetchall()
            meta = conn.execute(
                "SELECT revision, usage_json FROM facts_meta "
                "WHERE session_id = ? AND branch_id = ?",
                (session_id, branch_id),
            ).fetchone()
        return {
            "values": {str(row["key"]): str(row["value"]) for row in rows},
            "revision": int(meta["revision"]) if meta else 0,
            "usage": self._loads(meta["usage_json"], {}) if meta else {},
        }

    def save_facts(
        self,
        session_id: str,
        *,
        branch_id: str = MAIN_BRANCH,
        values: dict,
        revision: int,
        usage: dict,
    ) -> None:
        """Полная замена набора фактов ветки — состояние живёт в агенте."""
        with self._lock, self._connect() as conn, conn:
            conn.execute(
                "DELETE FROM facts WHERE session_id = ? AND branch_id = ?",
                (session_id, branch_id),
            )
            conn.executemany(
                "INSERT INTO facts (session_id, branch_id, key, value) VALUES (?, ?, ?, ?)",
                [(session_id, branch_id, key, str(value)) for key, value in values.items()],
            )
            conn.execute(
                "INSERT INTO facts_meta (session_id, branch_id, revision, usage_json) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(session_id, branch_id) DO UPDATE SET "
                "revision = excluded.revision, usage_json = excluded.usage_json",
                (
                    session_id,
                    branch_id,
                    int(revision),
                    json.dumps(usage or {}, ensure_ascii=False, sort_keys=True),
                ),
            )

    # --------------------------------------------------------------- messages

    def append(
        self, session_id: str, role: str, content: str, branch_id: str = MAIN_BRANCH
    ) -> None:
        with self._lock, self._connect() as conn, conn:
            self._ensure_branch(conn, session_id, branch_id)
            conn.execute(
                "INSERT INTO messages (session_id, branch_id, role, content) VALUES (?, ?, ?, ?)",
                (session_id, branch_id, role, content),
            )

    def next_turn_index(self, session_id: str, branch_id: str = MAIN_BRANCH) -> int:
        with self._lock, self._connect() as conn:
            value = conn.execute(
                "SELECT COALESCE(MAX(turn_index), 0) + 1 FROM request_log "
                "WHERE session_id = ? AND branch_id = ?",
                (session_id, branch_id),
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
        branch_id: str = MAIN_BRANCH,
    ) -> None:
        with self._lock, self._connect() as conn, conn:
            self._ensure_branch(conn, session_id, branch_id)
            conn.execute(
                "INSERT INTO messages (session_id, branch_id, turn_id, role, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, branch_id, request_id, "user", user_text),
            )
            conn.execute(
                "INSERT INTO messages (session_id, branch_id, turn_id, role, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, branch_id, request_id, "assistant", assistant_text),
            )
            self._insert_log(
                conn,
                request_id=request_id,
                session_id=session_id,
                branch_id=branch_id,
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
        branch_id: str = MAIN_BRANCH,
    ) -> None:
        with self._lock, self._connect() as conn, conn:
            self._ensure_branch(conn, session_id, branch_id)
            self._insert_log(
                conn,
                request_id=request_id,
                session_id=session_id,
                branch_id=branch_id,
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
        branch_id: str,
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
            "request_id, session_id, branch_id, turn_index, provider, model, status, "
            "metrics_json, usage_json, attempts_json, error"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_id,
                session_id,
                branch_id,
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

    def load_request_logs(
        self, session_id: str, branch_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Без ``branch_id`` — логи всей сессии: расход считается по сессии."""
        with self._lock, self._connect() as conn:
            if branch_id is None:
                rows = conn.execute(
                    "SELECT * FROM request_log WHERE session_id = ? "
                    "ORDER BY created_at, turn_index",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM request_log WHERE session_id = ? AND branch_id = ? "
                    "ORDER BY turn_index, created_at",
                    (session_id, branch_id),
                ).fetchall()
        return [self._row_to_log(row) for row in rows]

    def clear(self, session_id: str, branch_id: str | None = None) -> None:
        """Без ``branch_id`` чистит всю сессию вместе с ветками и фактами."""
        with self._lock, self._connect() as conn, conn:
            if branch_id is None:
                for table in ("messages", "request_log", "branches", "facts", "facts_meta"):
                    conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
                return
            for table in ("messages", "request_log", "facts", "facts_meta"):
                conn.execute(
                    f"DELETE FROM {table} WHERE session_id = ? AND branch_id = ?",
                    (session_id, branch_id),
                )

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
            "branch_id": row["branch_id"],
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
        for index in range(3):
            store.append_exchange_with_log(
                session_id="s1",
                request_id=f"r{index}",
                turn_index=index + 1,
                user_text=f"u{index}",
                assistant_text=f"a{index}",
                provider="fake",
                model="fake-model",
                status="ok",
                metrics={},
                usage={"total_tokens": 5, "reported": True},
                attempts=[],
            )
        assert len(store.load("s1")) == 6
        assert store.next_turn_index("s1") == 4

        # Checkpoint после первого обмена → две независимые ветки.
        store.create_branch("s1", branch_id="b1", parent_branch_id="main", fork_index=2)
        store.create_branch("s1", branch_id="b2", parent_branch_id="main", fork_index=2)
        store.append("s1", "user", "только в b1", branch_id="b1")
        store.append("s1", "user", "только в b2", branch_id="b2")

        b1 = [content for _, content in store.load("s1", branch_id="b1")]
        b2 = [content for _, content in store.load("s1", branch_id="b2")]
        assert b1 == ["u0", "a0", "только в b1"], b1
        assert b2 == ["u0", "a0", "только в b2"], b2
        assert len(store.load("s1")) == 6, "main не должна видеть сообщения веток"
        assert store.next_turn_index("s1", "b1") == 1

        store.save_facts("s1", values={"цель": "ТЗ"}, revision=1, usage={"total_tokens": 7})
        store.create_branch("s1", branch_id="b3", parent_branch_id="main", fork_index=0)
        assert store.load_facts("s1", "b3")["values"] == {"цель": "ТЗ"}
        assert store.load("s1", branch_id="b3") == []
        assert {row["branch_id"] for row in store.list_branches("s1")} == {
            "main", "b1", "b2", "b3"
        }

        store.clear("s1", branch_id="b1")
        assert store.load("s1", branch_id="b1") == [("user", "u0"), ("assistant", "a0")]
        store.clear("s1")
        assert store.load("s1") == [] and store.list_branches("s1") == []
        print("history_store self-check OK")
    finally:
        os.remove(path)


if __name__ == "__main__":
    _demo()
