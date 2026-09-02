"""Проверка: text-режим day2 восстанавливает жёлтый retry-баннер HEAD-версии.

tools/llm/gemini.call_gemini_with_retries печатает retry-сообщение без цвета;
day2 передаёт retry_logger=_retry_banner, чтобы видео-рекордер, который парсит
ANSI-цвета (ANSI_COLORS, "33" — жёлтый), не увидел молча изменившийся кадр на
редкой ветке 429/503.
"""

import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import tools.llm.gemini as gemini
from tools.llm.gemini import GeminiCallError

DAY2 = (
    Path(__file__).resolve().parents[1]
    / "day02-response-control"
    / "day2_response_control.py"
)


@pytest.fixture(scope="module")
def day2():
    spec = importlib.util.spec_from_file_location("day2_response_control", DAY2)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self._json = {}
        self.text = text

    def json(self):
        return self._json


def test_retry_banner_has_yellow_ansi(monkeypatch, day2):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResponse(status_code=429, text="rate limited")

    monkeypatch.setattr(gemini.requests, "post", fake_post)
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(GeminiCallError):
        day2.run_experiment(
            word_limit=100,
            stop_sequence="<END_RESPONSE>",
            max_output_tokens=256,
            model_chain=["m"],
            quiet=False,
        )
    out = buf.getvalue()
    # жёлтый ANSI + текст баннера (tools/llm печатает его без \033[33m)
    assert "\033[33m  [m] HTTP 429, жду" in out
    assert calls  # сеть реально вызывалась
