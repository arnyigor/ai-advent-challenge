"""Compare two real models on exactly the same persisted task state."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from task_state import TaskState, _required

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.llm.client import Client
from tools.llm.deepseek import DEFAULT_MODEL as DEEPSEEK_MODEL

WORMSOFT_MODEL = "openai/gpt-oss:20b"
WORMSOFT_DEFAULT_BASE_URL = "https://ai.wormsoft.ru/api/gpt"
SYSTEM = (
    "Ты исполнитель одного этапа задачи. Работай только в указанном текущем этапе, "
    "учитывай результаты прошлых этапов и не объявляй переход состояния. "
    "Верни конкретный результат текущего шага на русском языке, до 900 символов."
)


@dataclass(frozen=True)
class ModelResult:
    id: str
    label: str
    provider: str
    model: str
    answer: str
    elapsed_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


def build_prompt(state: TaskState) -> str:
    return (
        f"Цель задачи: {state.objective}\n"
        f"Текущий этап: {state.stage}\n"
        f"Текущий шаг: {state.current_step}\n"
        f"Ожидаемое действие после результата: {state.expected_action}\n"
        f"Результаты прошлых этапов: {json.dumps(state.artifacts, ensure_ascii=False)}\n\n"
        "Подготовь результат текущего шага."
    )


class ModelComparator:
    def compare(self, state: TaskState) -> dict:
        if state.paused:
            raise ValueError("Для сравнения сначала продолжите задачу")
        if state.stage == "done":
            raise ValueError("Задача завершена: активного шага для сравнения нет")
        prompt = build_prompt(state)
        results = [self._deepseek(prompt), self._wormsoft(prompt)]
        return {
            "state_version": state.version,
            "stage": state.stage,
            "prompt": prompt,
            "results": [result.to_dict() for result in results],
        }

    @staticmethod
    def _deepseek(prompt: str) -> ModelResult:
        started = time.perf_counter()
        data = Client(f"deepseek:{DEEPSEEK_MODEL}", quiet=True).call(
            prompt, {"temperature": 0.1, "maxOutputTokens": 700}, system_instruction=SYSTEM,
        )
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        answer = "".join(str(part.get("text", "")) for part in parts if not part.get("thought"))
        return ModelResult(
            "deepseek", "DeepSeek V4 Flash", "deepseek", DEEPSEEK_MODEL,
            _required("answer", answer, 10000), round((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _wormsoft(prompt: str) -> ModelResult:
        key = (os.environ.get("WORMSOFT_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("WORMSOFT_API_KEY не задан")
        started = time.perf_counter()
        base_url = (os.environ.get("WORMSOFT_BASE_URL") or WORMSOFT_DEFAULT_BASE_URL).rstrip("/")
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": WORMSOFT_MODEL,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 700,
            },
            timeout=90,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Wormsoft HTTP {response.status_code}")
        try:
            answer = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Wormsoft вернул неожиданный формат ответа") from exc
        return ModelResult(
            "wormsoft", "GPT-OSS 20B · Wormsoft", "wormsoft", WORMSOFT_MODEL,
            _required("answer", answer, 10000), round((time.perf_counter() - started) * 1000),
        )
