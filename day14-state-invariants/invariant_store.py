"""Immutable-style invariant contract loaded separately from conversation history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Invariant:
    id: str
    category: str
    title: str
    rule: str
    conflict_terms: tuple[str, ...]
    required_terms: tuple[str, ...] = ()

    def public_dict(self) -> dict:
        return {"id": self.id, "category": self.category, "title": self.title, "rule": self.rule}


class InvariantStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> tuple[int, tuple[Invariant, ...]]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("invariants"), list):
            raise ValueError("Некорректный контракт инвариантов")
        invariants = tuple(self._parse(item) for item in raw["invariants"])
        ids = [item.id for item in invariants]
        if not invariants or len(ids) != len(set(ids)):
            raise ValueError("Инварианты должны иметь уникальные id")
        return int(raw.get("version", 1)), invariants

    @staticmethod
    def _parse(raw: dict) -> Invariant:
        required = ("id", "category", "title", "rule", "conflict_terms")
        if not isinstance(raw, dict) or any(not raw.get(key) for key in required):
            raise ValueError("У инварианта отсутствуют обязательные поля")
        return Invariant(
            id=str(raw["id"]), category=str(raw["category"]),
            title=str(raw["title"]), rule=str(raw["rule"]),
            conflict_terms=tuple(str(x).casefold() for x in raw["conflict_terms"]),
            required_terms=tuple(str(x).casefold() for x in raw.get("required_terms", [])),
        )
