"""Тесты сетевого слоя tools/llm/gemini.py без реальной сети.

requests.post подменяется fake-объектом, time.sleep — no-op, ключ — через
monkeypatch окружения. Покрывают ветки, которые ретраи и fallback-цепочка
проходят только в бою: 429/503 (ретрай), 400 (мгновенный проброс),
сеть (ретрай), исчерпание попыток, битый ключ.
"""

import pytest
import requests

import tools.llm.gemini as gemini
from tools.llm.gemini import (
    MAX_RETRIES_PER_MODEL,
    GeminiCallError,
    GeminiFatalError,
    call_gemini_with_retries,
    extract_response,
    has_gemini_api_key,
)


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._json = body if body is not None else {}
        self.text = text

    def json(self):
        return self._json


def _patch_network(monkeypatch, responder):
    """Подменяет requests.post и time.sleep; возвращает список вызовов post."""
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers, timeout))
        result = responder()
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(gemini.requests, "post", fake_post)
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return calls


def _ok_body(text="ok"):
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {"candidatesTokenCount": len(text)},
    }


# --- extract_response -------------------------------------------------------


def test_extract_response_empty_candidates():
    r = extract_response({"candidates": []})
    assert r == {"text": "", "finish_reason": "NO_CANDIDATES", "output_tokens": None}


def test_extract_response_no_candidates_key():
    r = extract_response({})
    assert r == {"text": "", "finish_reason": "NO_CANDIDATES", "output_tokens": None}


def test_extract_response_block_reason_present():
    r = extract_response(
        {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}
    )
    assert r["text"] == ""
    assert r["finish_reason"] == "NO_CANDIDATES (blockReason=SAFETY)"
    assert r["output_tokens"] is None


def test_extract_response_candidate_without_content():
    r = extract_response({"candidates": [{"finishReason": "STOP"}]})
    assert r["text"] == ""
    assert r["finish_reason"] == "STOP"


def test_extract_response_multiple_parts_joined():
    data = {
        "candidates": [
            {
                "content": {"parts": [{"text": "foo"}, {"text": "bar"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"candidatesTokenCount": 7},
    }
    r = extract_response(data)
    assert r["text"] == "foobar"
    assert r["finish_reason"] == "STOP"
    assert r["output_tokens"] == 7


def test_extract_response_missing_usage_metadata():
    data = {
        "candidates": [{"content": {"parts": [{"text": "hi"}]}, "finishReason": "STOP"}]
    }
    assert extract_response(data)["output_tokens"] is None


# --- has_gemini_api_key -----------------------------------------------------


def test_has_key_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert not has_gemini_api_key()


def test_has_key_empty(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert not has_gemini_api_key()


def test_has_key_whitespace(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert not has_gemini_api_key()


def test_has_key_real(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza...")
    assert has_gemini_api_key()


# --- call_gemini_with_retries ------------------------------------------------


def test_missing_key_fails_without_network(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        gemini.requests,
        "post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")),
    )

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        call_gemini_with_retries("model", "prompt")


def test_429_retries_then_exhausts(monkeypatch):
    calls = _patch_network(
        monkeypatch, lambda: FakeResponse(status_code=429, text="rate limited")
    )

    with pytest.raises(GeminiCallError) as ei:
        call_gemini_with_retries("m", "p", quiet=True)
    assert ei.value.status_code == 429
    assert len(calls) == MAX_RETRIES_PER_MODEL  # 2 попытки, потом исчерпание


def test_429_then_success(monkeypatch):
    state = {"n": 0}

    def responder():
        state["n"] += 1
        if state["n"] == 1:
            return FakeResponse(status_code=429, text="x")
        return FakeResponse(status_code=200, body=_ok_body())

    calls = _patch_network(monkeypatch, responder)
    data = call_gemini_with_retries("m", "p", quiet=True)
    assert data["candidates"][0]["content"]["parts"][0]["text"] == "ok"
    assert len(calls) == 2


def test_400_raises_immediately_no_retries(monkeypatch):
    """400 INVALID_ARGUMENT — фатально: падает за один вызов, не перебирая цепочку."""
    calls = _patch_network(
        monkeypatch, lambda: FakeResponse(status_code=400, text="bad argument")
    )

    with pytest.raises(GeminiFatalError) as ei:
        call_gemini_with_retries("m", "p", quiet=True)
    assert ei.value.status_code == 400
    assert len(calls) == 1


def test_503_retries_then_exhausts(monkeypatch):
    calls = _patch_network(
        monkeypatch, lambda: FakeResponse(status_code=503, text="overloaded")
    )

    with pytest.raises(GeminiCallError) as ei:
        call_gemini_with_retries("m", "p", quiet=True)
    assert ei.value.status_code == 503
    assert len(calls) == MAX_RETRIES_PER_MODEL


def test_network_error_retries_then_exhausts(monkeypatch):
    def boom():
        raise requests.exceptions.ConnectionError("net down")

    calls = _patch_network(monkeypatch, boom)
    with pytest.raises(GeminiCallError):
        call_gemini_with_retries("m", "p", quiet=True)
    assert len(calls) == MAX_RETRIES_PER_MODEL


def test_401_raises_fatal_immediately(monkeypatch):
    """401/403 — GeminiFatalError (не GeminiCallError): не ретраится и не двигает
    цепочку моделей, всплывает сразу к обработчику эксперимента."""
    calls = _patch_network(
        monkeypatch, lambda: FakeResponse(status_code=401, text="denied")
    )

    with pytest.raises(GeminiFatalError, match="401"):
        call_gemini_with_retries("m", "p", quiet=True)
    assert len(calls) == 1
