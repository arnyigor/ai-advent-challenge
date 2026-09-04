"""Реестр LLM-провайдеров: единая точка, где новый день регистрирует провайдера,
не трогая if/elif по имени внутри самого дня.

Раньше split_model_spec/model_label/has-key-проверки были продублированы
трижды (day3_reasoning_modes.py, web_server.py — каждый со своей копией).
Теперь это один словарь PROVIDERS ниже; добавление 3-го провайдера (день N) —
это одна новая запись здесь, а не новый if/elif в трёх местах.

Формат model spec: "provider:model" (например "deepseek:deepseek-v4-flash").
Без префикса провайдер по умолчанию — gemini (обратная совместимость с Day 2).
"""

from dataclasses import dataclass
from typing import Callable

from tools.llm import deepseek, gemini, huggingface

DEFAULT_PROVIDER = "gemini"


@dataclass(frozen=True)
class Provider:
    name: str
    default_model: str
    has_key: Callable[[], bool]
    missing_key_message: str
    call_with_retries: Callable
    call_stream_with_retries: Callable


PROVIDERS = {
    "gemini": Provider(
        name="gemini",
        default_model=gemini.PRIMARY_MODEL,
        has_key=gemini.has_gemini_api_key,
        missing_key_message="GEMINI_API_KEY is not set",
        call_with_retries=gemini.call_gemini_with_retries,
        call_stream_with_retries=gemini.call_gemini_stream_with_retries,
    ),
    "deepseek": Provider(
        name="deepseek",
        default_model=deepseek.DEFAULT_MODEL,
        has_key=deepseek.has_deepseek_api_key,
        missing_key_message="DEEPSEEK_API_KEY is not set",
        call_with_retries=deepseek.call_deepseek_with_retries,
        call_stream_with_retries=deepseek.call_deepseek_stream_with_retries,
    ),
    "hf": Provider(
        name="hf",
        default_model=huggingface.DEFAULT_MODEL,
        has_key=huggingface.has_hf_token,
        missing_key_message="HF_TOKEN is not set",
        call_with_retries=huggingface.call_huggingface_with_retries,
        call_stream_with_retries=huggingface.call_huggingface_stream_with_retries,
    ),
}


def split_model_spec(model_spec):
    """"provider:model" -> (provider, model); без префикса -> (gemini, model_spec).

    Провайдер не валидируется здесь (даже незарегистрированный проходит) —
    ошибка "Unknown LLM provider" всплывает позже, в resolve_provider(),
    в точке фактического вызова."""
    if isinstance(model_spec, str) and ":" in model_spec:
        provider, model = model_spec.split(":", 1)
        return provider.strip().lower(), model.strip()
    return DEFAULT_PROVIDER, model_spec


def resolve_provider(name):
    provider = PROVIDERS.get(name)
    if provider is None:
        raise RuntimeError(f"Unknown LLM provider: {name}")
    return provider


def model_label(model_spec):
    provider, model = split_model_spec(model_spec)
    return model if provider == DEFAULT_PROVIDER else f"{provider}:{model}"


def _provider_for_key_check(model_spec):
    """Незарегистрированный/отсутствующий провайдер -> проверка как для gemini
    (сохраняет поведение до появления реестра: было hardcoded 'deepseek' vs
    всё остальное)."""
    provider_name, _model = split_model_spec(model_spec)
    return PROVIDERS.get(provider_name) or PROVIDERS[DEFAULT_PROVIDER]


def has_key_for(model_spec):
    return _provider_for_key_check(model_spec).has_key()


def missing_key_message(model_spec):
    return _provider_for_key_check(model_spec).missing_key_message
