"""Declarative, deterministic lifecycle for Day 15."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def required(label: str, value: str, maximum: int = 12_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label}: нужна непустая строка не длиннее {maximum} символов")
    return value.strip()


@dataclass(frozen=True)
class TransitionRule:
    action: str
    source: str
    target: str
    artifact: str


@dataclass(frozen=True)
class LifecycleContract:
    version: int
    initial_state: str
    terminal_states: frozenset[str]
    titles: dict[str, str]
    descriptions: dict[str, str]
    transitions: dict[str, dict[str, TransitionRule]]

    @classmethod
    def load(cls, path: str | Path) -> "LifecycleContract":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        states = raw.get("states")
        if not isinstance(states, list) or not states:
            raise ValueError("Контракт должен содержать состояния")
        ids = [str(item.get("id", "")) for item in states]
        if any(not item for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("Состояния должны иметь уникальные непустые id")
        known = set(ids)
        initial = str(raw.get("initial_state", ""))
        terminals = frozenset(str(item) for item in raw.get("terminal_states", []))
        if initial not in known or not terminals or not terminals <= known:
            raise ValueError("Некорректные начальное или терминальные состояния")
        titles, descriptions, transitions = {}, {}, {}
        for item in states:
            state_id = str(item["id"])
            titles[state_id] = required("title", str(item.get("title", "")), 100)
            descriptions[state_id] = required("description", str(item.get("description", "")), 300)
            transitions[state_id] = {}
            for action, spec in item.get("transitions", {}).items():
                target = str(spec.get("target", ""))
                artifact = str(spec.get("artifact", ""))
                if target not in known or not action or not artifact:
                    raise ValueError(f"Некорректный переход {state_id}.{action}")
                transitions[state_id][action] = TransitionRule(action, state_id, target, artifact)
        if any(transitions[state] for state in terminals):
            raise ValueError("Терминальное состояние не может иметь переходы")
        return cls(int(raw.get("version", 1)), initial, terminals, titles, descriptions, transitions)

    def allowed_actions(self, state: str) -> tuple[str, ...]:
        return tuple(self.transitions[state])

    def public_dict(self) -> dict:
        return {
            "version": self.version,
            "initial_state": self.initial_state,
            "terminal_states": sorted(self.terminal_states),
            "states": [
                {"id": state, "title": self.titles[state], "description": self.descriptions[state],
                 "actions": [{"id": rule.action, "target": rule.target, "artifact": rule.artifact}
                             for rule in self.transitions[state].values()]}
                for state in self.titles
            ],
        }


class TransitionRejected(ValueError):
    def __init__(self, code: str, message: str, allowed_actions: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.allowed_actions = allowed_actions


class TransitionGuard:
    def __init__(self, contract: LifecycleContract):
        self.contract = contract

    def check(self, *, state: str, action: str, paused: bool) -> TransitionRule:
        allowed = self.contract.allowed_actions(state)
        if paused:
            raise TransitionRejected("paused", "Задача на паузе; сначала выполните resume", allowed)
        if state in self.contract.terminal_states:
            raise TransitionRejected("already_completed", "Завершённую задачу нельзя изменить", ())
        rule = self.contract.transitions[state].get(action)
        if rule is None:
            expected = ", ".join(allowed) or "нет"
            raise TransitionRejected(
                "invalid_transition",
                f"Действие {action!r} недопустимо в состоянии {state!r}. Сейчас разрешено: {expected}",
                allowed,
            )
        return rule
