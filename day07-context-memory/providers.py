"""LLM-провайдеры Day 7: Gemini -> Wormsoft -> RouterAI."""

from __future__ import annotations

import os
import threading
from typing import Sequence

import requests

from agent import (
    AgentConfig,
    Message,
    ProviderCancelledError,
    ProviderError,
    ProviderReply,
    TokenUsage,
)
from tools.llm._transport import LLMCancelledError
from tools.llm.client import Client
from tools.llm.deepseek import (
    DEFAULT_MODEL as DEEPSEEK_DEFAULT_MODEL,
    DeepSeekFatalError,
    DeepSeekModelUnavailableError,
    DeepSeekRetryableError,
    has_deepseek_api_key,
)
from tools.llm.gemini import (
    MODEL_CHAIN,
    GeminiCallError,
    has_gemini_api_key,
)
from tools.llm.runner import run_with_model_fallback

def _split_answer_and_thoughts(data: object) -> tuple[str, str]:
    """Separates Gemini/DeepSeek 'thought' parts (from includeThoughts /
    reasoning_content, see providers below) from the final answer text.
    Kept local to day06: tools.llm.gemini.extract_response()'s return shape
    is locked by tests shared with every other day, so it doesn't carry a
    reasoning key."""
    if not isinstance(data, dict):
        return "", ""
    candidates = data.get("candidates") or []
    if not candidates:
        return "", ""
    parts = candidates[0].get("content", {}).get("parts", [])
    answer = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    thought = "".join(p.get("text", "") for p in parts if p.get("thought"))
    return answer, thought


def _conversation_prompt(messages: Sequence[Message]) -> str:
    labels = {"user": "Пользователь", "assistant": "Ассистент"}
    transcript = "\n".join(
        f"{labels.get(message.role, message.role)}: {message.content}" for message in messages
    )
    return f"Продолжи диалог.\n\n{transcript}\nАссистент:"


def _read_nonnegative_int(usage: dict, names: Sequence[str]) -> int | None:
    """Выбирает первое присутствующее имя; bool не считается int."""
    for name in names:
        if name not in usage:
            continue
        value = usage[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value
    return None


def _normalize_usage(
    raw_usage: object,
    *,
    input_names: Sequence[str],
    output_names: Sequence[str],
    total_name: str,
    reasoning_names: Sequence[str] = (),
    reasoning_detail_names: Sequence[str] = (),
) -> TokenUsage:
    """Нормализует только точные provider-счётчики, не оценивая токены."""
    if not isinstance(raw_usage, dict):
        return TokenUsage()

    input_tokens = _read_nonnegative_int(raw_usage, input_names)
    output_tokens = _read_nonnegative_int(raw_usage, output_names)
    if input_tokens is None or output_tokens is None:
        return TokenUsage()

    if total_name in raw_usage:
        total_tokens = _read_nonnegative_int(raw_usage, (total_name,))
        if total_tokens is None:
            return TokenUsage()
    else:
        total_tokens = input_tokens + output_tokens

    reasoning_tokens = _read_nonnegative_int(raw_usage, reasoning_names)
    if reasoning_tokens is None:
        for detail_name in reasoning_detail_names:
            details = raw_usage.get(detail_name)
            if not isinstance(details, dict):
                continue
            reasoning_tokens = _read_nonnegative_int(details, ("reasoning_tokens",))
            if reasoning_tokens is not None:
                break
    if reasoning_tokens is None:
        reasoning_tokens = 0

    try:
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            reported=True,
            reasoning_tokens=reasoning_tokens,
        )
    except (TypeError, ValueError):
        return TokenUsage()


class ClientProvider:
    """Провайдер поверх tools.llm.Client: общий путь retries/cancellation/
    model-fallback уже реализован в реестре tools/llm — Gemini и DeepSeek
    отдают ответ в одинаковой форме (candidates/usageMetadata), поэтому им
    достаточно одной реализации generate() с разными константами."""

    def __init__(self, *, provider_id, label, model_chain, fallback_exc, has_key):
        self.id = provider_id
        self.label = label
        self.default_model = model_chain[0]
        self._model_chain = model_chain
        self._fallback_exc = fallback_exc
        self._has_key = has_key

    def available(self) -> bool:
        return self._has_key()

    def model_options(self) -> list[str]:
        return list(self._model_chain)

    def generate(
        self,
        messages: Sequence[Message],
        config: AgentConfig,
        cancel_event: threading.Event,
    ) -> ProviderReply:
        prompt = _conversation_prompt(messages)
        model_chain = self._model_chain
        if config.model and config.model in model_chain:
            model_chain = [config.model] + [m for m in model_chain if m != config.model]

        def call(model: str):
            client = Client(f"{self.id}:{model}", quiet=True, cancel_event=cancel_event)
            return client.call(
                prompt,
                {
                    "temperature": config.temperature,
                    "maxOutputTokens": config.max_output_tokens,
                    "topP": config.top_p,
                    "topK": config.top_k,
                    "thinkingConfig": {
                        "thinkingLevel": config.thinking_level,
                        "includeThoughts": True,
                    },
                },
                system_instruction=config.system_prompt,
            )

        try:
            data, model_used, _attempts = run_with_model_fallback(
                model_chain,
                call,
                fallback_exc=self._fallback_exc,
            )
            answer_text, thought_text = _split_answer_and_thoughts(data)
            usage = _normalize_usage(
                data.get("usageMetadata") if isinstance(data, dict) else None,
                input_names=("promptTokenCount",),
                output_names=("candidatesTokenCount",),
                total_name="totalTokenCount",
                reasoning_names=("thoughtsTokenCount",),
            )
            return ProviderReply(
                answer_text, self.id, model_used, usage, reasoning=thought_text
            )
        except LLMCancelledError:
            raise ProviderCancelledError(f"{self.label}: запрос отменён") from None
        except Exception as exc:
            raise ProviderError(f"{self.label} недоступен: {type(exc).__name__}") from None


class GeminiProvider(ClientProvider):
    def __init__(self):
        super().__init__(
            provider_id="gemini",
            label="Gemini",
            model_chain=MODEL_CHAIN,
            fallback_exc=GeminiCallError,
            has_key=has_gemini_api_key,
        )


class DeepSeekProvider(ClientProvider):
    def __init__(self):
        super().__init__(
            provider_id="deepseek",
            label="DeepSeek",
            model_chain=[DEEPSEEK_DEFAULT_MODEL],
            fallback_exc=(
                DeepSeekFatalError,
                DeepSeekRetryableError,
                DeepSeekModelUnavailableError,
            ),
            has_key=has_deepseek_api_key,
        )


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        label: str,
        key_env: str,
        model: str,
        base_url: str | None = None,
        base_url_env: str | None = None,
        timeout: int = 60,
    ):
        self.id = provider_id
        self.label = label
        self.key_env = key_env
        self.default_model = model
        self._base_url = base_url
        self._base_url_env = base_url_env
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        configured = os.environ.get(self._base_url_env or "") if self._base_url_env else None
        return (configured or self._base_url or "").rstrip("/")

    def available(self) -> bool:
        return bool((os.environ.get(self.key_env) or "").strip() and self.base_url)

    def model_options(self) -> list[str]:
        return [self.default_model]

    def generate(
        self,
        messages: Sequence[Message],
        config: AgentConfig,
        cancel_event: threading.Event,
    ) -> ProviderReply:
        if cancel_event.is_set():
            raise ProviderCancelledError(f"{self.label}: запрос отменён")
        if not self.available():
            raise ProviderError(f"{self.label}: конфигурация не задана")
        model = config.model if config.model in self.model_options() else self.default_model
        payload_messages = [{"role": "system", "content": config.system_prompt}]
        payload_messages.extend(
            {"role": message.role, "content": message.content} for message in messages
        )
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.environ[self.key_env]}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": payload_messages,
                    "temperature": config.temperature,
                    "max_tokens": config.max_output_tokens,
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            if cancel_event.is_set():
                raise ProviderCancelledError(f"{self.label}: запрос отменён") from None
            raise ProviderError(f"{self.label}: ошибка сети {type(exc).__name__}") from None
        if cancel_event.is_set():
            raise ProviderCancelledError(f"{self.label}: запрос отменён")
        if response.status_code != 200:
            raise ProviderError(f"{self.label}: HTTP {response.status_code}")
        try:
            data = response.json()
            message = data["choices"][0]["message"]
            text = message["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.label}: неожиданный формат ответа") from None
        reasoning = message.get("reasoning_content") or "" if isinstance(message, dict) else ""
        usage = _normalize_usage(
            data.get("usage") if isinstance(data, dict) else None,
            input_names=("prompt_tokens", "input_tokens"),
            output_names=("completion_tokens", "output_tokens"),
            total_name="total_tokens",
            reasoning_names=("reasoning_tokens",),
            reasoning_detail_names=(
                "completion_tokens_details",
                "output_tokens_details",
            ),
        )
        return ProviderReply(str(text), self.id, model, usage, reasoning=str(reasoning))


def create_default_providers():
    """Единая цепочка провайдеров для web и CLI."""
    return [
        DeepSeekProvider(),
        GeminiProvider(),
        OpenAICompatibleProvider(
            provider_id="wormsoft",
            label="Wormsoft",
            key_env="WORMSOFT_API_KEY",
            base_url_env="WORMSOFT_BASE_URL",
            model="deepseek-ai/deepseek-v4-flash",
        ),
        OpenAICompatibleProvider(
            provider_id="routerai",
            label="RouterAI",
            key_env="ROUTERAI_API_KEY",
            base_url="https://routerai.ru/api/v1",
            model="qwen/qwen3.8-27b",
        ),
    ]


def public_provider_status() -> list[dict]:
    return [
        {
            "id": provider.id,
            "label": provider.label,
            "model": provider.default_model,
            "available": provider.available(),
            "models": provider.model_options(),
        }
        for provider in create_default_providers()
    ]
