"""Стриминг (SSE) для gemini.py и deepseek.py поверх общего tools/llm/_transport.

httpx.AsyncClient подменяется фейком, который отдаёт заранее заданные строки
`data: ...` построчно — сеть не участвует. Цель: закрепить поведение
стримингового пути (общий transport.stream_sse), раз оно раньше не было
покрыто тестами вообще.
"""

import asyncio

import httpx
import pytest

import tools.llm.deepseek as deepseek
import tools.llm.gemini as gemini


class FakeStreamResponse:
    def __init__(self, status_code, lines, body=b""):
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._body


class FakeStreamContext:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class FakeAsyncClient:
    def __init__(self, response, calls):
        self._response = response
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, json=None, headers=None):
        self._calls.append((method, url, json, headers))
        return FakeStreamContext(self._response)


def _patch_httpx(monkeypatch, status_code, lines, body=b""):
    calls = []
    response = FakeStreamResponse(status_code, lines, body)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda timeout=None: FakeAsyncClient(response, calls)
    )
    return calls


# --- gemini stream ------------------------------------------------------


def test_gemini_stream_accumulates_text_and_usage(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    lines = [
        'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}',
        'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]},"finishReason":"STOP"}],'
        '"usageMetadata":{"promptTokenCount":3,"candidatesTokenCount":2}}',
        "",
    ]
    _patch_httpx(monkeypatch, 200, lines)

    deltas = []
    states = []
    data = asyncio.run(
        gemini._call_gemini_stream_once(
            "m",
            "prompt",
            on_text=deltas.append,
            on_state=states.append,
        )
    )
    resp = gemini.extract_response(data)
    assert resp["text"] == "Hello"
    assert resp["finish_reason"] == "STOP"
    assert deltas == ["Hel", "lo"]
    assert states == ["connecting", "waiting_first_token", "streaming", "finalizing", "complete"]
    usage = gemini.extract_usage(data)
    assert usage == {"prompt_tokens": 3, "output_tokens": 2}


def test_gemini_stream_status_error_raises_fatal(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _patch_httpx(monkeypatch, 401, [], body=b"denied")
    with pytest.raises(gemini.GeminiFatalError):
        asyncio.run(gemini._call_gemini_stream_once("m", "prompt"))


# --- deepseek stream ------------------------------------------------------


def test_deepseek_stream_accumulates_text_and_usage(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":3,"completion_tokens":2}}',
        "data: [DONE]",
        "",
    ]
    _patch_httpx(monkeypatch, 200, lines)

    deltas = []
    data = asyncio.run(
        deepseek._call_deepseek_stream_once(
            "deepseek-v4-flash", "prompt", on_text=deltas.append
        )
    )
    assert data["candidates"][0]["content"]["parts"][0]["text"] == "Hello"
    assert data["candidates"][0]["finishReason"] == "STOP"
    assert data["usageMetadata"] == {"promptTokenCount": 3, "candidatesTokenCount": 2}
    assert deltas == ["Hel", "lo"]


def test_deepseek_stream_status_error_raises_retryable(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _patch_httpx(monkeypatch, 503, [], body=b"overloaded")
    with pytest.raises(deepseek.DeepSeekRetryableError):
        asyncio.run(deepseek._call_deepseek_stream_once("m", "prompt"))
