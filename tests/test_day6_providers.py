import sys
import threading
from pathlib import Path

import pytest

DAY06_DIR = Path(__file__).resolve().parents[1] / "day06-first-agent"
if str(DAY06_DIR) not in sys.path:
    sys.path.insert(0, str(DAY06_DIR))

from agent import (
    AgentConfig,
    Message,
    ProviderCancelledError,
    TokenUsage,
)
from providers import (
    DeepSeekProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    create_default_providers,
)
from tools.llm._transport import LLMCancelledError


def _openai_provider(monkeypatch, response):
    monkeypatch.setenv("TEST_LLM_KEY", "secret-not-for-output")
    monkeypatch.setattr("providers.requests.post", response)
    return OpenAICompatibleProvider(
        provider_id="test",
        label="Test",
        key_env="TEST_LLM_KEY",
        base_url="https://example.test/v1/",
        model="test-model",
    )


def _response(payload):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return payload

    return Response()


def test_default_provider_order_is_locked():
    assert [provider.id for provider in create_default_providers()] == [
        "deepseek",
        "gemini",
        "wormsoft",
        "routerai",
    ]


def test_openai_provider_sends_agent_config_and_full_history(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _response({"choices": [{"message": {"content": "готово"}}]})

    provider = _openai_provider(monkeypatch, fake_post)
    config = AgentConfig(
        system_prompt="Тестовая системная инструкция",
        temperature=0.25,
        max_output_tokens=321,
    )
    history = [Message("user", "Привет"), Message("assistant", "Здравствуйте")]

    reply = provider.generate(history, config, threading.Event())

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["json"] == {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "Тестовая системная инструкция"},
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Здравствуйте"},
        ],
        "temperature": 0.25,
        "max_tokens": 321,
    }
    assert captured["timeout"] == 60
    assert reply.text == "готово"
    assert "secret-not-for-output" not in repr(reply)


def test_openai_provider_maps_usage_and_parses_json_once(monkeypatch):
    json_calls = 0

    class Response:
        status_code = 200

        @staticmethod
        def json():
            nonlocal json_calls
            json_calls += 1
            return {
                "choices": [{"message": {"content": "ответ"}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            }

    provider = _openai_provider(monkeypatch, lambda *_args, **_kwargs: Response())

    reply = provider.generate(
        [Message("user", "вопрос")], AgentConfig(), threading.Event()
    )

    assert json_calls == 1
    assert reply.usage == TokenUsage(11, 7, 18, True)


def test_openai_provider_accepts_input_output_usage_names(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "ответ"}}],
        "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
    }
    provider = _openai_provider(
        monkeypatch, lambda *_args, **_kwargs: _response(payload)
    )

    reply = provider.generate(
        [Message("user", "вопрос")], AgentConfig(), threading.Event()
    )

    assert reply.usage == TokenUsage(5, 3, 8, True)


@pytest.mark.parametrize(
    "raw_usage",
    [
        None,
        {},
        {"prompt_tokens": 1},
        {"prompt_tokens": "1", "completion_tokens": 2, "total_tokens": 3},
        {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3},
        {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
        {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": None},
    ],
)
def test_openai_provider_treats_missing_or_invalid_usage_as_unreported(
    monkeypatch, raw_usage
):
    payload = {"choices": [{"message": {"content": "ответ"}}]}
    if raw_usage is not None:
        payload["usage"] = raw_usage
    provider = _openai_provider(
        monkeypatch, lambda *_args, **_kwargs: _response(payload)
    )

    reply = provider.generate(
        [Message("user", "вопрос")], AgentConfig(), threading.Event()
    )

    assert reply.usage == TokenUsage()


def test_gemini_provider_sends_agent_config_and_maps_usage(monkeypatch):
    captured = {}
    data = {
        "candidates": [
            {
                "content": {"parts": [{"text": "готово"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 13,
            "candidatesTokenCount": 4,
            "totalTokenCount": 17,
            "thoughtsTokenCount": 2,
        },
    }

    class FakeClient:
        def __init__(self, model, quiet, cancel_event):
            captured["client"] = {
                "model": model,
                "quiet": quiet,
                "cancel_event": cancel_event,
            }

        def call(self, prompt, generation_config, *, system_instruction):
            captured["call"] = {
                "prompt": prompt,
                "generation_config": generation_config,
                "system_instruction": system_instruction,
            }
            return data

    def fake_run(model_chain, call, *, fallback_exc):
        captured["runner"] = {
            "model_chain": tuple(model_chain),
            "fallback_exc": fallback_exc,
        }
        model = model_chain[0]
        return call(model), model, [{"model": model, "status": "ok"}]

    monkeypatch.setattr("providers.Client", FakeClient)
    monkeypatch.setattr("providers.run_with_model_fallback", fake_run)
    config = AgentConfig(
        system_prompt="Gemini system",
        temperature=0.4,
        max_output_tokens=456,
        thinking_level="high",
    )
    cancel_event = threading.Event()

    reply = GeminiProvider().generate(
        [Message("user", "Первый"), Message("assistant", "Второй")],
        config,
        cancel_event,
    )

    assert captured["client"]["model"].startswith("gemini:")
    assert captured["client"]["quiet"] is True
    assert captured["client"]["cancel_event"] is cancel_event
    assert captured["call"]["generation_config"] == {
        "temperature": 0.4,
        "maxOutputTokens": 456,
        "thinkingConfig": {"thinkingLevel": "high"},
    }
    assert captured["call"]["system_instruction"] == "Gemini system"
    assert "Пользователь: Первый" in captured["call"]["prompt"]
    assert "Ассистент: Второй" in captured["call"]["prompt"]
    assert captured["runner"]["model_chain"]
    assert reply.text == "готово"
    assert reply.model == captured["runner"]["model_chain"][0]
    assert reply.usage == TokenUsage(13, 4, 17, True, 2)


def test_deepseek_provider_sends_agent_config_and_maps_usage(monkeypatch):
    captured = {}
    data = {
        "candidates": [
            {
                "content": {"parts": [{"text": "готово"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 9,
            "candidatesTokenCount": 6,
            "totalTokenCount": 15,
        },
    }

    class FakeClient:
        def __init__(self, model, quiet, cancel_event):
            captured["client"] = {"model": model, "quiet": quiet}

        def call(self, prompt, generation_config, *, system_instruction):
            captured["call"] = {"generation_config": generation_config}
            return data

    def fake_run(model_chain, call, *, fallback_exc):
        captured["runner"] = {"model_chain": tuple(model_chain)}
        model = model_chain[0]
        return call(model), model, [{"model": model, "status": "ok"}]

    monkeypatch.setattr("providers.Client", FakeClient)
    monkeypatch.setattr("providers.run_with_model_fallback", fake_run)

    reply = DeepSeekProvider().generate(
        [Message("user", "вопрос")], AgentConfig(), threading.Event()
    )

    assert captured["client"]["model"].startswith("deepseek:")
    assert captured["runner"]["model_chain"]
    assert reply.provider == "deepseek"
    assert reply.text == "готово"
    assert reply.usage == TokenUsage(9, 6, 15, True)


def test_gemini_provider_handles_missing_usage(monkeypatch):
    data = {
        "candidates": [
            {
                "content": {"parts": [{"text": "без usage"}]},
                "finishReason": "STOP",
            }
        ]
    }

    class FakeClient:
        def __init__(self, _model, quiet, cancel_event):
            assert quiet is True
            assert isinstance(cancel_event, threading.Event)

        def call(self, _prompt, _generation_config, *, system_instruction):
            assert system_instruction == AgentConfig().system_prompt
            return data

    def fake_run(model_chain, call, *, fallback_exc):
        model = model_chain[0]
        return call(model), model, []

    monkeypatch.setattr("providers.Client", FakeClient)
    monkeypatch.setattr("providers.run_with_model_fallback", fake_run)

    reply = GeminiProvider().generate(
        [Message("user", "вопрос")], AgentConfig(), threading.Event()
    )

    assert reply.text == "без usage"
    assert reply.usage == TokenUsage()


@pytest.mark.parametrize(
    ("raw_usage", "expected_reasoning"),
    [
        (
            {
                "prompt_tokens": 5,
                "completion_tokens": 7,
                "total_tokens": 12,
                "reasoning_tokens": 3,
            },
            3,
        ),
        (
            {
                "prompt_tokens": 5,
                "completion_tokens": 7,
                "total_tokens": 12,
                "completion_tokens_details": {"reasoning_tokens": 4},
            },
            4,
        ),
        (
            {
                "input_tokens": 5,
                "output_tokens": 7,
                "total_tokens": 12,
                "output_tokens_details": {"reasoning_tokens": 6},
            },
            6,
        ),
    ],
)
def test_openai_provider_maps_reported_reasoning_tokens(
    monkeypatch, raw_usage, expected_reasoning
):
    provider = _openai_provider(
        monkeypatch,
        lambda *_args, **_kwargs: _response(
            {"choices": [{"message": {"content": "ответ"}}], "usage": raw_usage}
        ),
    )

    reply = provider.generate(
        [Message("user", "вопрос")], AgentConfig(), threading.Event()
    )

    assert reply.usage.reasoning_tokens == expected_reasoning


def test_openai_provider_honors_cancellation_before_request(monkeypatch):
    provider = _openai_provider(
        monkeypatch,
        lambda *_args, **_kwargs: pytest.fail("HTTP request must not start"),
    )
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(ProviderCancelledError):
        provider.generate([Message("user", "вопрос")], AgentConfig(), cancel_event)


def test_openai_provider_honors_cancellation_after_blocking_request(monkeypatch):
    cancel_event = threading.Event()

    def fake_post(*_args, **_kwargs):
        cancel_event.set()
        return _response({"choices": [{"message": {"content": "late"}}]})

    provider = _openai_provider(monkeypatch, fake_post)

    with pytest.raises(ProviderCancelledError):
        provider.generate([Message("user", "вопрос")], AgentConfig(), cancel_event)


def test_gemini_provider_maps_llm_cancellation(monkeypatch):
    class CancelledClient:
        def __init__(self, _model, quiet, cancel_event):
            assert quiet is True
            assert cancel_event.is_set()

        def call(self, *_args, **_kwargs):
            raise LLMCancelledError("cancelled")

    def fake_run(model_chain, call, *, fallback_exc):
        assert fallback_exc
        return call(model_chain[0])

    monkeypatch.setattr("providers.Client", CancelledClient)
    monkeypatch.setattr("providers.run_with_model_fallback", fake_run)
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(ProviderCancelledError):
        GeminiProvider().generate(
            [Message("user", "вопрос")], AgentConfig(), cancel_event
        )
