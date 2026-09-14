"""Small adapters for the repository's existing LLM client."""

from __future__ import annotations

import os

import requests

from agent import ProviderReply
from tools.llm.client import Client
from tools.llm.deepseek import DEFAULT_MODEL as DEEPSEEK_MODEL, has_deepseek_api_key
from tools.llm.gemini import MODEL_CHAIN, has_gemini_api_key

WORMSOFT_MODEL = "openai/gpt-oss:20b"
WORMSOFT_DEFAULT_BASE_URL = "https://ai.wormsoft.ru/api/gpt"


def _wormsoft_generate(*, system: str, messages: list[dict[str, str]]) -> ProviderReply:
    base_url = (os.environ.get("WORMSOFT_BASE_URL") or WORMSOFT_DEFAULT_BASE_URL).rstrip("/")
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {os.environ['WORMSOFT_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": WORMSOFT_MODEL,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0.1,
            "max_tokens": 512,
        },
        timeout=90,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Wormsoft HTTP {response.status_code}")
    try:
        answer = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Wormsoft вернул неожиданный формат ответа") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Wormsoft вернул пустой ответ")
    return ProviderReply(answer.strip(), "wormsoft", WORMSOFT_MODEL)


class LiveProvider:
    def __init__(self, provider_id: str = "auto"):
        if provider_id not in {"auto", "deepseek", "gemini", "wormsoft"}:
            raise ValueError("provider_id должен быть auto, deepseek, gemini или wormsoft")
        self.provider_id = provider_id

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ProviderReply:
        transcript = "\n".join(
            f"{'Пользователь' if m['role'] == 'user' else 'Ассистент'}: {m['content']}"
            for m in messages
        ) + "\nАссистент:"
        candidates = []
        if self.provider_id in {"auto", "deepseek"} and has_deepseek_api_key():
            candidates.append(("deepseek", DEEPSEEK_MODEL))
        if self.provider_id in {"auto", "gemini"} and has_gemini_api_key():
            candidates.append(("gemini", MODEL_CHAIN[0]))
        if self.provider_id in {"auto", "wormsoft"} and (os.environ.get("WORMSOFT_API_KEY") or "").strip():
            candidates.append(("wormsoft", WORMSOFT_MODEL))
        if not candidates:
            raise RuntimeError("Нет API-ключа выбранного провайдера")
        failures = []
        for provider_id, model in candidates:
            try:
                if provider_id == "wormsoft":
                    return _wormsoft_generate(system=system, messages=messages)
                data = Client(f"{provider_id}:{model}", quiet=True).call(
                    transcript,
                    {"temperature": 0.1, "maxOutputTokens": 512},
                    system_instruction=system,
                )
                parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
                answer = "".join(str(part.get("text", "")) for part in parts if not part.get("thought"))
                if not answer.strip():
                    raise RuntimeError("Провайдер вернул пустой ответ")
                return ProviderReply(answer.strip(), provider_id, model)
            except Exception as exc:
                failures.append(f"{provider_id}: {type(exc).__name__}")
        raise RuntimeError("Все провайдеры недоступны: " + ", ".join(failures))
