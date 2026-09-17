"""Minimal OpenAI-compatible RouterAI client for Qwen3.8-27B."""
from __future__ import annotations
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODEL = "qwen/qwen3.8-27b"
ENDPOINT = "https://routerai.ru/api/v1/chat/completions"


class RouterAIClient:
    provider = "RouterAI"
    model = MODEL

    @property
    def available(self) -> bool:
        return bool(os.environ.get("ROUTERAI_API_KEY", "").strip())

    def generate(self, request: str, invariants: list[dict]) -> str:
        key = os.environ.get("ROUTERAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("ROUTERAI_API_KEY не настроен")
        rules = "\n".join(f"- [{item['id']}] {item['rule']}" for item in invariants)
        payload = {"model": self.model, "temperature": 0.2, "max_tokens": 500, "messages": [
            {"role": "system", "content": "Ты технический ассистент. Предложи краткое практическое решение только в рамках перечисленных инвариантов. Не предлагай их обход.\n" + rules},
            {"role": "user", "content": request},
        ]}
        http_request = Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urlopen(http_request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            answer = data["choices"][0]["message"]["content"]
            if not str(answer).strip():
                raise ValueError("Пустой ответ")
            return str(answer).strip()
        except HTTPError as exc:
            raise RuntimeError(f"RouterAI: HTTP {exc.code}") from None
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"RouterAI: ошибка сети {type(exc).__name__}") from None
        except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise RuntimeError("RouterAI: неожиданный формат ответа") from None
