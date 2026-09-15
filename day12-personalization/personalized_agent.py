"""Day 12: automatic profile injection and ordered role workflow."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAY11 = ROOT / "day11-memory-layers"
for directory in (str(ROOT), str(DAY11)):
    if directory not in sys.path:
        sys.path.insert(0, directory)

from agent import MemoryAgent
from memory_store import LAYERS, MemoryStore, _required
from profile_store import ProfileStore

ROLE_INSTRUCTIONS = {
    "analyst": "Уточни требования и критерии готовности для задачи.",
    "architect": "Предложи структуру решения и ключевые интерфейсы.",
    "developer": "Реализуй решение: дай конкретный код или последовательность изменений.",
    "reviewer": "Проверь предложенное решение, найди дефекты и предложи исправления.",
}


class PersonalizedAgent(MemoryAgent):
    def __init__(self, store: MemoryStore, profiles: ProfileStore, provider):
        super().__init__(store, provider)
        self.profiles = profiles

    def build_request(self, *, user_id: str, session_id: str, task_id: str, user_text: str, include: tuple[str, ...] = LAYERS) -> dict:
        request = super().build_request(user_id=user_id, session_id=session_id, task_id=task_id, user_text=user_text, include=include)
        profile = self.profiles.get(user_id)
        lines = ["[ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ — применяется к каждому запросу]"]
        labels = {"address": "Обращение", "style": "Стиль", "format": "Формат", "constraints": "Ограничения"}
        for key, label in labels.items():
            if profile[key]:
                lines.append(f"{label}: {profile[key]}")
        request["system"] += "\n\n" + "\n".join(lines)
        request["profile_used"] = profile
        request["workflow"] = self.plan(user_text, profile)
        return request

    @staticmethod
    def plan(text: str, profile: dict) -> list[str]:
        trigger = profile["trigger"].casefold()
        return profile["roles"].copy() if trigger and trigger in text.casefold() else []

    def ask(self, *, user_id: str, session_id: str, task_id: str, user_text: str, include: tuple[str, ...] = LAYERS) -> dict:
        request = self.build_request(user_id=user_id, session_id=session_id, task_id=task_id, user_text=user_text, include=include)
        steps = []
        for role in request["workflow"]:
            system = request["system"] + f"\n\n[РОЛЬ: {role}]\n{ROLE_INSTRUCTIONS[role]}"
            messages = [*request["messages"]]
            if steps:
                messages.append({"role": "user", "content": "Результаты предыдущих ролей:\n" + "\n".join(f"{item['role']}: {item['output']}" for item in steps)})
            reply = self.provider.generate(system=system, messages=messages)
            steps.append({"role": role, "output": _required("output", reply.text, 32000), "provider": reply.provider, "model": reply.model})
        if steps:
            answer = "\n\n".join(f"{item['role']}: {item['output']}" for item in steps)
            provider, model = steps[-1]["provider"], steps[-1]["model"]
        else:
            reply = self.provider.generate(system=request["system"], messages=request["messages"])
            answer = _required("answer", reply.text, 32000)
            provider, model = reply.provider, reply.model
        self.store.append_turn(user_id=user_id, session_id=session_id, user_text=user_text, answer=answer)
        return {"answer": answer, "provider": provider, "model": model, "context": request, "steps": steps}
