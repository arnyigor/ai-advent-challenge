"""Compare DeepSeek and Qwen 27B without granting either state mutation access."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from task_lifecycle import LifecycleContract, required
from task_store import TaskState

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.llm.client import Client
from tools.llm.deepseek import DEFAULT_MODEL as DEEPSEEK_MODEL

ROUTERAI_MODEL = "qwen/qwen3.8-27b"
ROUTERAI_ENDPOINT = "https://routerai.ru/api/v1/chat/completions"
SYSTEM = (
    "Ты ассистент с контролируемым жизненным циклом. Проанализируй запрос только в текущем состоянии. "
    "Не утверждай, что состояние изменено: решение принимает внешний TransitionGuard. "
    "Ответь по-русски до 700 символов и явно назови предлагаемое действие."
)


@dataclass(frozen=True)
class ModelResult:
    id: str
    label: str
    provider: str
    model: str
    status: str
    answer: str
    elapsed_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


def build_prompt(state: TaskState, contract: LifecycleContract, request: str) -> str:
    return (
        f"Цель: {state.objective}\nТекущее состояние: {state.state}\n"
        f"Пауза: {'да' if state.paused else 'нет'}\nВерсия: {state.version}\n"
        f"Разрешённые действия: {', '.join(contract.allowed_actions(state.state)) or 'нет'}\n"
        f"Артефакты: {json.dumps(state.artifacts, ensure_ascii=False)}\n"
        f"Запрос пользователя: {required('request', request)}\n\n"
        "Предложи реакцию ассистента. Не изменяй состояние."
    )


class ModelComparator:
    def __init__(self, contract: LifecycleContract):
        self.contract = contract

    def compare(self, state: TaskState, request: str) -> dict:
        prompt = build_prompt(state, self.contract, request)
        results = []
        for model_id, call in (("deepseek", self._deepseek), ("routerai", self._routerai)):
            try:
                results.append(call(prompt))
            except RuntimeError as exc:
                label, provider, model = (("DeepSeek V4 Flash", "DeepSeek", DEEPSEEK_MODEL)
                                          if model_id == "deepseek" else
                                          ("Qwen3.8-27B", "RouterAI", ROUTERAI_MODEL))
                results.append(ModelResult(model_id, label, provider, model, "unavailable", str(exc), 0))
        return {"state_version": state.version, "state": state.state, "prompt": prompt,
                "state_changed": False, "results": [item.to_dict() for item in results]}

    @staticmethod
    def _deepseek(prompt: str) -> ModelResult:
        started = time.perf_counter()
        try:
            data = Client(f"deepseek:{DEEPSEEK_MODEL}", quiet=True).call(
                prompt, {"temperature": 0.1, "maxOutputTokens": 600}, system_instruction=SYSTEM)
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            answer = "".join(str(part.get("text", "")) for part in parts if not part.get("thought"))
            answer = required("answer", answer)
        except Exception as exc:
            raise RuntimeError(f"DeepSeek недоступен: {type(exc).__name__}") from None
        return ModelResult("deepseek", "DeepSeek V4 Flash", "DeepSeek", DEEPSEEK_MODEL, "ok", answer,
                           round((time.perf_counter() - started) * 1000))

    @staticmethod
    def _routerai(prompt: str) -> ModelResult:
        key = os.environ.get("ROUTERAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("ROUTERAI_API_KEY не настроен")
        payload = {"model": ROUTERAI_MODEL, "temperature": 0.1, "max_tokens": 600,
                   "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
        request = Request(ROUTERAI_ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST",
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
            answer = required("answer", str(data["choices"][0]["message"]["content"]))
        except HTTPError as exc:
            raise RuntimeError(f"RouterAI HTTP {exc.code}") from None
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"RouterAI недоступен: {type(exc).__name__}") from None
        except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise RuntimeError("RouterAI вернул неожиданный ответ") from None
        return ModelResult("routerai", "Qwen3.8-27B", "RouterAI", ROUTERAI_MODEL, "ok", answer,
                           round((time.perf_counter() - started) * 1000))
