"""Second verified DeepSeek model for live Day 12 comparison."""

from __future__ import annotations

import personalized_agent  # Sets the repository and Day 11 import paths.
from agent import ProviderReply
from providers import LiveProvider
from tools.llm.client import Client

REASONER_MODEL = "deepseek-reasoner"


class ReasonerProvider:
    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ProviderReply:
        transcript = "\n".join(
            f"{'Пользователь' if item['role'] == 'user' else 'Ассистент'}: {item['content']}"
            for item in messages
        ) + "\nАссистент:"
        data = Client(f"deepseek:{REASONER_MODEL}", quiet=True).call(
            transcript,
            {"temperature": 0.1, "maxOutputTokens": 2048, "thinkingConfig": {"thinkingLevel": "high"}},
            system_instruction=system,
        )
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        answer = "".join(str(part.get("text", "")) for part in parts if not part.get("thought"))
        if not answer.strip():
            raise RuntimeError("DeepSeek Reasoner вернул пустой ответ")
        return ProviderReply(answer.strip(), "deepseek", REASONER_MODEL)
