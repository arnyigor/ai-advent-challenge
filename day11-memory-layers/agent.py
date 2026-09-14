"""Day 11 agent: explicit three-layer memory context, independent of provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from memory_store import LAYERS, MemoryStore, _required

BASE_INSTRUCTION = (
    "Ты полезный ассистент. Используй переданные слои памяти как контекст. "
    "Не выдумывай отсутствующие факты. Если сведений нет, так и скажи. "
    "Долговременный профиль влияет на стиль ответа; рабочая память относится "
    "только к активной задаче; краткосрочная — только к текущему диалогу."
)


@dataclass(frozen=True)
class ProviderReply:
    text: str
    provider: str
    model: str


class Provider(Protocol):
    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ProviderReply: ...


def _render_facts(title: str, facts: dict[str, str]) -> str:
    lines = [f"- {key}: {value}" for key, value in sorted(facts.items())]
    return f"[{title}]\n" + ("\n".join(lines) if lines else "(пусто)")


class MemoryAgent:
    def __init__(self, store: MemoryStore, provider: Provider, *, recent_messages: int = 6):
        if recent_messages < 1:
            raise ValueError("recent_messages должен быть положительным")
        self.store = store
        self.provider = provider
        self.recent_messages = recent_messages

    def build_request(
        self, *, user_id: str, session_id: str, task_id: str,
        user_text: str, include: tuple[str, ...] = LAYERS,
    ) -> dict:
        _required("user_id", user_id, 80)
        _required("session_id", session_id, 80)
        _required("task_id", task_id, 80)
        user_text = _required("user_text", user_text, 8000)
        if any(layer not in LAYERS for layer in include) or len(set(include)) != len(include):
            raise ValueError("include должен содержать уникальные известные слои")

        snapshot = self.store.snapshot(user_id=user_id, session_id=session_id, task_id=task_id)
        selected = {
            "short": snapshot["short"] if "short" in include else {"facts": {}, "messages": []},
            "working": snapshot["working"] if "working" in include else {},
            "long": snapshot["long"] if "long" in include else {},
        }
        system_parts = [BASE_INSTRUCTION]
        if "long" in include:
            system_parts.append(_render_facts("ДОЛГОВРЕМЕННАЯ ПАМЯТЬ", selected["long"]))
        if "working" in include:
            system_parts.append(_render_facts("РАБОЧАЯ ПАМЯТЬ", selected["working"]))
        if "short" in include:
            system_parts.append(_render_facts("ЗАМЕТКИ ТЕКУЩЕЙ СЕССИИ", selected["short"]["facts"]))
        messages = [*selected["short"]["messages"][-self.recent_messages:], {"role": "user", "content": user_text}]
        return {
            "system": "\n\n".join(system_parts),
            "messages": messages,
            "included_layers": list(include),
            "memory_used": {
                "short": {"facts": selected["short"]["facts"], "messages": selected["short"]["messages"][-self.recent_messages:]},
                "working": selected["working"],
                "long": selected["long"],
            },
        }

    def ask(
        self, *, user_id: str, session_id: str, task_id: str,
        user_text: str, include: tuple[str, ...] = LAYERS,
    ) -> dict:
        request = self.build_request(
            user_id=user_id, session_id=session_id, task_id=task_id,
            user_text=user_text, include=include,
        )
        reply = self.provider.generate(system=request["system"], messages=request["messages"])
        answer = _required("answer", reply.text, 32000)
        self.store.append_turn(
            user_id=user_id, session_id=session_id, user_text=user_text, answer=answer,
        )
        return {
            "answer": answer,
            "provider": reply.provider,
            "model": reply.model,
            "context": request,
        }
