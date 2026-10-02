"""Day 25: SQLite history of the dialogue, resumable by session_id."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChatStore:
    """Append-only message log; nothing here is a fact store."""

    def __init__(self, directory: str | Path):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "chat.db"
        self._lock = threading.RLock()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                "session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
                "role TEXT NOT NULL, content TEXT NOT NULL, payload_json TEXT, "
                "created_at TEXT NOT NULL)"
            )

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex[:12]
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO sessions VALUES (?, ?)", (session_id, _now()))
        return session_id

    def session_exists(self, session_id: str) -> bool:
        if not isinstance(session_id, str) or not session_id.strip():
            return False
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def append(self, session_id: str, role: str, content: str, payload: dict | None = None) -> None:
        if role not in ("user", "assistant"):
            raise ValueError("role должен быть user или assistant")
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO messages (session_id, role, content, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    role,
                    content,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    _now(),
                ),
            )

    def history(self, session_id: str, limit: int | None = None) -> list[dict]:
        if limit is not None:
            query = ("SELECT role, content, payload_json, created_at FROM messages "
                     "WHERE session_id = ? ORDER BY id DESC LIMIT ?")
            parameters: tuple = (session_id, limit)
        else:
            query = "SELECT role, content, payload_json, created_at FROM messages WHERE session_id = ? ORDER BY id"
            parameters = (session_id,)
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, parameters).fetchall()
        if limit is not None:
            rows = list(reversed(rows))
        items = []
        for row in rows:
            items.append(
                {
                    "role": row["role"],
                    "content": row["content"],
                    "payload": json.loads(row["payload_json"]) if row["payload_json"] else None,
                    "created_at": row["created_at"],
                }
            )
        return items

    def commit_turn(self, session_id, message, payload, state_store, previous_version):
        """Commit the exchange and task state together across two SQLite files.

        Both files use SQLite's default rollback journal, allowing ATTACH's
        multi-database transaction to commit or roll back the entire turn.
        """
        state = payload['task_state']
        encoded = json.dumps(payload, ensure_ascii=False)
        with self._lock, state_store._lock, closing(sqlite3.connect(self.path)) as conn:
            conn.execute('ATTACH DATABASE ? AS memory', (str(state_store.path),))
            try:
                conn.execute('BEGIN IMMEDIATE')
                current = conn.execute('SELECT version FROM memory.task_states WHERE session_id = ?',
                                       (session_id,)).fetchone()
                if current is None or current[0] != previous_version:
                    raise ValueError('Состояние изменилось: повторите сообщение')
                if state['version'] != previous_version:
                    conn.execute('UPDATE memory.task_states SET goal=?, clarified_json=?, '
                                 'constraints_json=?, terms_json=?, version=? WHERE session_id=?',
                                 (state['goal'], json.dumps(state['clarified'], ensure_ascii=False),
                                  json.dumps(state['constraints'], ensure_ascii=False),
                                  json.dumps(state['terms'], ensure_ascii=False), state['version'], session_id))
                    conn.execute('INSERT INTO memory.state_events (session_id,event,version,details) VALUES (?,?,?,?)',
                                 (session_id, 'updated' if previous_version else 'created',
                                  state['version'], message[:200]))
                conn.executemany('INSERT INTO messages (session_id,role,content,payload_json,created_at) '
                                 'VALUES (?,?,?,?,?)',
                                 [(session_id, 'user', message, None, _now()),
                                  (session_id, 'assistant', payload['answer'], encoded, _now())])
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def sessions(self) -> list[dict]:
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT s.session_id, s.created_at, COUNT(m.id) AS messages "
                "FROM sessions s LEFT JOIN messages m ON m.session_id = s.session_id "
                "GROUP BY s.session_id ORDER BY s.created_at DESC, s.session_id"
            ).fetchall()
        return [dict(row) for row in rows]
