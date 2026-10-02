"""Day 25: task state — цель, уточнения, ограничения и термины диалога.

Состояние хранится отдельно от истории чата (см. MEMORY_AND_STATE.md):
его обновляет код после успешной проверки, а не сама модель. Инвариант
append-only не даёт ассистенту «потерять» уже зафиксированные факты.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

GOAL_LIMIT = 500
ITEM_LIMIT = 300
MAX_ITEMS = 40
LISTS = ("clarified", "constraints", "terms")


@dataclass(frozen=True)
class TaskState:
    session_id: str
    goal: str
    clarified: tuple[str, ...]
    constraints: tuple[str, ...]
    terms: tuple[str, ...]
    version: int

    def to_dict(self) -> dict:
        return asdict(self)

    def as_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _clean_list(items, label: str) -> tuple[str, ...]:
    if items is None:
        return ()
    if not isinstance(items, list):
        raise ValueError(f"{label} должен быть массивом строк")
    cleaned: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip() or len(item) > ITEM_LIMIT:
            raise ValueError(f"{label}: нужна непустая строка до {ITEM_LIMIT} символов")
        cleaned.append(" ".join(item.split()))
    unique = tuple(dict.fromkeys(cleaned))
    if len(unique) > MAX_ITEMS:
        raise ValueError(f"{label}: не больше {MAX_ITEMS} пунктов")
    return unique


def normalize_state(session_id: str, payload, previous: TaskState | None) -> TaskState:
    """Validate a model-produced state against the schema (no invariant decisions here)."""
    if not isinstance(payload, dict):
        raise ValueError("Состояние должно быть JSON-объектом")
    goal = payload.get("goal")
    if not isinstance(goal, str) or not goal.strip() or len(goal) > GOAL_LIMIT:
        raise ValueError(f"goal обязана быть непустой строкой до {GOAL_LIMIT} символов")
    lists = {name: _clean_list(payload.get(name), name) for name in LISTS}
    return TaskState(
        session_id=session_id,
        goal=" ".join(goal.split()),
        version=previous.version + 1 if previous is not None else 1,
        **lists,
    )


def merge_state(previous: TaskState | None, candidate: TaskState) -> TaskState:
    """Enforce the append-only invariant in code: nothing recorded is ever dropped.

    The model proposes items; previously recorded items are kept verbatim and
    only genuinely new items (case-insensitive) are appended.
    """
    if previous is None or previous.version == 0:
        return candidate
    merged = {}
    for name in LISTS:
        kept = list(getattr(previous, name))
        known = {item.casefold() for item in kept}
        for item in candidate_items(candidate, name):
            if item.casefold() not in known:
                kept.append(item)
                known.add(item.casefold())
        if len(kept) > MAX_ITEMS:
            raise ValueError(f"{name}: превышен лимит {MAX_ITEMS} пунктов")
        merged[name] = tuple(kept)
    return TaskState(
        session_id=previous.session_id,
        goal=previous.goal,
        version=previous.version + 1,
        **merged,
    )


def candidate_items(state: TaskState, name: str) -> tuple[str, ...]:
    return getattr(state, name)


class TaskStateStore:
    """SQLite persistence with optimistic version checks and an audit trail."""

    def __init__(self, directory: str | Path):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "task_state.db"
        self._lock = threading.RLock()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS task_states ("
                "session_id TEXT PRIMARY KEY, goal TEXT NOT NULL, "
                "clarified_json TEXT NOT NULL, constraints_json TEXT NOT NULL, "
                "terms_json TEXT NOT NULL, version INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS state_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
                "event TEXT NOT NULL, version INTEGER NOT NULL, details TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )

    def create(self, session_id: str) -> TaskState:
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO task_states VALUES (?, '', '[]', '[]', '[]', 0)",
                (session_id,),
            )
        return self.get(session_id)

    def get(self, session_id: str) -> TaskState:
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM task_states WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return self.create(session_id)
        return TaskState(
            session_id=session_id,
            goal=row["goal"],
            clarified=tuple(json.loads(row["clarified_json"])),
            constraints=tuple(json.loads(row["constraints_json"])),
            terms=tuple(json.loads(row["terms_json"])),
            version=row["version"],
        )

    def save(self, state: TaskState, *, previous_version: int, event: str, details: str = "") -> TaskState:
        with self._lock, closing(sqlite3.connect(self.path)) as connection, connection:
            current = connection.execute(
                "SELECT version FROM task_states WHERE session_id = ?", (state.session_id,)
            ).fetchone()
            if current is None or current[0] != previous_version:
                raise ValueError(
                    f"Состояние устарело: ожидается версия {previous_version}, в базе {current[0] if current else 'нет записи'}"
                )
            connection.execute(
                "UPDATE task_states SET goal = ?, clarified_json = ?, constraints_json = ?, "
                "terms_json = ?, version = ? WHERE session_id = ?",
                (
                    state.goal,
                    json.dumps(state.clarified, ensure_ascii=False),
                    json.dumps(state.constraints, ensure_ascii=False),
                    json.dumps(state.terms, ensure_ascii=False),
                    state.version,
                    state.session_id,
                ),
            )
            connection.execute(
                "INSERT INTO state_events (session_id, event, version, details) VALUES (?, ?, ?, ?)",
                (state.session_id, event, state.version, details[:2000]),
            )
        return state

    def events(self, session_id: str) -> list[dict]:
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT event, version, details, created_at FROM state_events "
                "WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]
