"""User-owned personalization, separate from the three memory layers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

FIELDS = ("address", "style", "format", "constraints")
ROLES = ("analyst", "architect", "developer", "reviewer")
DEFAULT_PROFILE = {**{field: "" for field in FIELDS}, "trigger": "", "roles": []}


def validate_profile(profile: dict) -> dict:
    if not isinstance(profile, dict) or set(profile) != set(DEFAULT_PROFILE):
        raise ValueError("Профиль должен содержать address, style, format, constraints, trigger, roles")
    clean = {}
    for field in (*FIELDS, "trigger"):
        value = profile[field]
        if not isinstance(value, str) or len(value) > 500:
            raise ValueError(f"{field}: строка до 500 символов")
        clean[field] = value.strip()
    roles = profile["roles"]
    if not isinstance(roles, list) or len(roles) > 4 or any(role not in ROLES for role in roles) or len(set(roles)) != len(roles):
        raise ValueError("roles: уникальные роли из analyst, architect, developer, reviewer")
    if bool(clean["trigger"]) != bool(roles):
        raise ValueError("Для сценария нужны и триггер, и хотя бы одна роль")
    clean["roles"] = roles.copy()
    return clean


class ProfileStore:
    def __init__(self, directory: str | Path):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "profiles.db"
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS profiles (user_id TEXT PRIMARY KEY, data TEXT NOT NULL)")

    @staticmethod
    def _user(user_id: str) -> str:
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 80:
            raise ValueError("user_id: непустая строка до 80 символов")
        return user_id.strip()

    def get(self, user_id: str) -> dict:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT data FROM profiles WHERE user_id = ?", (self._user(user_id),)).fetchone()
        return json.loads(row[0]) if row else {**DEFAULT_PROFILE, "roles": []}

    def save(self, user_id: str, profile: dict) -> dict:
        clean = validate_profile(profile)
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT OR REPLACE INTO profiles (user_id, data) VALUES (?, ?)", (self._user(user_id), json.dumps(clean, ensure_ascii=False)))
        return clean
