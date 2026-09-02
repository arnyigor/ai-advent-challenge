"""Матрица классификации ошибок (шаг 4.1).

Три исхода вызова вместо двух:
  GeminiFatalError      — стоп немедленно (битый ключ, плохой аргумент)
  GeminiRetryableError  — повторить на той же модели (429/503/500/сеть)
  ModelUnavailableError — перейти к следующей модели, пауз нет (404)

Классификация идёт по error.status из тела (400 с NOT_FOUND = модель
недоступна), с фолбэком на HTTP-код. Все проверки офлайн (mock requests.post).
"""

import importlib.util
import json
from pathlib import Path

import pytest

import tools.llm.gemini as gemini
from tools.llm.gemini import (
    MAX_RETRIES_PER_MODEL,
    GeminiCallError,
    GeminiFatalError,
    GeminiRetryableError,
    ModelUnavailableError,
    call_gemini_with_retries,
    classify_error,
)

DAY2 = (
    Path(__file__).resolve().parents[1]
    / "day02-response-control"
    / "day2_response_control.py"
)


@pytest.fixture(scope="module")
def day2():
    spec = importlib.util.spec_from_file_location("day2_response_control", DAY2)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _err_body(status, code=400, message="boom"):
    return json.dumps({"error": {"code": code, "message": message, "status": status}})


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._json = body if body is not None else {}
        self.text = text

    def json(self):
        return self._json


def _ok_body(text="ok"):
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {"candidatesTokenCount": len(text)},
    }


def _patch_network(monkeypatch, responder):
    """Подменяет requests.post и time.sleep; возвращает (calls, sleeps)."""
    calls = []
    sleeps = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(url)
        result = responder(url)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(gemini.requests, "post", fake_post)
    monkeypatch.setattr(gemini.time, "sleep", sleeps.append)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return calls, sleeps


# --- classify_error: чистая единица ------------------------------------------


def test_classify_by_status_invalid_argument():
    assert classify_error(400, _err_body("INVALID_ARGUMENT")) is GeminiFatalError


def test_classify_by_status_failed_precondition():
    assert classify_error(400, _err_body("FAILED_PRECONDITION")) is GeminiFatalError


def test_classify_by_status_unauthenticated():
    assert classify_error(401, _err_body("UNAUTHENTICATED")) is GeminiFatalError


def test_classify_by_status_permission_denied():
    assert classify_error(403, _err_body("PERMISSION_DENIED")) is GeminiFatalError


def test_classify_by_status_not_found_400():
    """400 с NOT_FOUND = модель недоступна (status важнее HTTP-кода)."""
    assert classify_error(400, _err_body("NOT_FOUND")) is ModelUnavailableError


def test_classify_by_status_not_found_404():
    assert classify_error(404, _err_body("NOT_FOUND")) is ModelUnavailableError


def test_classify_by_status_resource_exhausted():
    assert classify_error(429, _err_body("RESOURCE_EXHAUSTED")) is GeminiRetryableError


def test_classify_by_status_unavailable():
    assert classify_error(503, _err_body("UNAVAILABLE")) is GeminiRetryableError


def test_classify_by_status_internal():
    assert classify_error(500, _err_body("INTERNAL")) is GeminiRetryableError


def test_classify_by_status_unknown():
    assert classify_error(500, _err_body("UNKNOWN")) is GeminiRetryableError


def test_classify_unparsable_4xx_is_fatal():
    assert classify_error(400, "not json at all") is GeminiFatalError


def test_classify_unparsable_5xx_is_retryable():
    assert classify_error(500, "not json at all") is GeminiRetryableError


def test_classify_429_unparsable_is_retryable():
    """429 без тела всё равно retryable — иначе ретрай квоты сломался бы."""
    assert classify_error(429, "") is GeminiRetryableError


def test_classify_unknown_4xx_unparsable_is_fatal():
    assert classify_error(418, "teapot") is GeminiFatalError


# --- call_gemini_with_retries: поведение на уровнях вызова -------------------


def test_call_400_fatal_stops_after_one(monkeypatch):
    calls, sleeps = _patch_network(
        monkeypatch,
        lambda u: FakeResponse(400, text=_err_body("INVALID_ARGUMENT", 400)),
    )
    with pytest.raises(GeminiFatalError):
        call_gemini_with_retries("m", "p", quiet=True)
    assert len(calls) == 1
    assert sleeps == []


def test_call_404_unavailable_next_model_no_sleep(monkeypatch):
    calls, sleeps = _patch_network(
        monkeypatch,
        lambda u: FakeResponse(404, text=_err_body("NOT_FOUND", 404)),
    )
    with pytest.raises(ModelUnavailableError):
        call_gemini_with_retries("m", "p", quiet=True)
    assert len(calls) == 1
    assert sleeps == []  # ждать бессмысленно — модель не появится


def test_call_429_retries_with_escalating_wait(monkeypatch):
    calls, sleeps = _patch_network(
        monkeypatch,
        lambda u: FakeResponse(429, text=_err_body("RESOURCE_EXHAUSTED", 429)),
    )
    with pytest.raises(GeminiRetryableError) as ei:
        call_gemini_with_retries("m", "p", quiet=True)
    assert ei.value.status_code == 429
    assert len(calls) == MAX_RETRIES_PER_MODEL
    assert sleeps == [10, 20]  # RETRY_WAIT_S * attempt


def test_call_429_then_success(monkeypatch):
    state = {"n": 0}

    def responder(url):
        state["n"] += 1
        if state["n"] == 1:
            return FakeResponse(429, text=_err_body("RESOURCE_EXHAUSTED", 429))
        return FakeResponse(200, body=_ok_body())

    calls, sleeps = _patch_network(monkeypatch, responder)
    data = call_gemini_with_retries("m", "p", quiet=True)
    assert data["candidates"][0]["content"]["parts"][0]["text"] == "ok"
    assert len(calls) == 2
    assert sleeps == [10]


def test_call_500_unparsable_retries(monkeypatch):
    calls, sleeps = _patch_network(
        monkeypatch, lambda u: FakeResponse(500, text="internal error, no json")
    )
    with pytest.raises(GeminiRetryableError):
        call_gemini_with_retries("m", "p", quiet=True)
    assert len(calls) == MAX_RETRIES_PER_MODEL


def test_call_connection_error_retries(monkeypatch):
    import requests

    def boom(url):
        raise requests.exceptions.ConnectionError("net down")

    calls, _sleeps = _patch_network(monkeypatch, boom)
    with pytest.raises(GeminiRetryableError):
        call_gemini_with_retries("m", "p", quiet=True)
    assert len(calls) == MAX_RETRIES_PER_MODEL


def test_gemini_call_error_is_still_gemini_error():
    """GeminiRetryableError и ModelUnavailableError — подклассы GeminiCallError:
    существующий `except GeminiCallError` в day2 продолжает их ловить."""
    assert issubclass(GeminiRetryableError, GeminiCallError)
    assert issubclass(ModelUnavailableError, GeminiCallError)
    assert not issubclass(GeminiFatalError, GeminiCallError)
    assert issubclass(GeminiFatalError, RuntimeError)


# --- цепочка моделей на уровне day2.run_experiment ----------------------------


def test_chain_404_then_success_moves_to_next_model(monkeypatch, day2):
    """Модель 1 недоступна (NOT_FOUND) → модель 2 отвечает: успех на модели 2,
    суммарный sleep = 0."""
    calls, sleeps = _patch_network(
        monkeypatch,
        lambda u: (
            FakeResponse(404, text=_err_body("NOT_FOUND", 404))
            if "models/m1" in u
            else FakeResponse(200, body=_ok_body("ok"))
        ),
    )
    result = day2.run_experiment(
        word_limit=100,
        stop_sequence="<END_RESPONSE>",
        max_output_tokens=256,
        model_chain=["m1", "m2"],
        quiet=True,
    )
    assert result["model_used"] == "m2"
    assert sleeps == []  # NOT_FOUND: пауз нет
    assert any("models/m1" in u for u in calls)
    assert any("models/m2" in u for u in calls)


def test_chain_fatal_aborts_second_model_not_tried(monkeypatch, day2):
    """INVALID_ARGUMENT на модели 1 — фатально: исключение уходит наверх,
    модель 2 не пробуется."""
    calls, _sleeps = _patch_network(
        monkeypatch,
        lambda u: (
            FakeResponse(400, text=_err_body("INVALID_ARGUMENT", 400))
            if "models/m1" in u
            else FakeResponse(200, body=_ok_body())
        ),
    )
    with pytest.raises(GeminiFatalError):
        day2.run_experiment(
            word_limit=100,
            stop_sequence="<END_RESPONSE>",
            max_output_tokens=256,
            model_chain=["m1", "m2"],
            quiet=True,
        )
    assert all("models/m1" in u for u in calls)
    assert not any("models/m2" in u for u in calls)
