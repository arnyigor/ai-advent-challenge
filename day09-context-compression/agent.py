"""Day 9 agent: persistent history with rolling summary compression.

Интерфейсы (web/CLI) знают только про :meth:`ChatAgent.ask`. Конфигурация,
политики, история, fallback, judge и учёт токенов остаются внутри агента.
"""

from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Protocol, Sequence
from uuid import uuid4

from context_manager import (
    CompressionConfig,
    ContextManager,
    SummaryState,
    render_summary_prompt,
)
from token_metrics import build_snapshot, count_text, history_text, load_model_config


DEFAULT_SYSTEM_PROMPT = (
    "Тебя зовут Дементий Вечеров. Ты — детектив в отставке из "
    "ретрофутуристического нуарного мегаполиса Нео-Порт, подрабатывающий "
    "чат-агентом между расследованиями. Если тебя спросят, кто ты — "
    "обязательно назови это имя и происхождение. Отвечай ясно, по существу "
    "и полезно — это важнее стиля. Изредка, где уместно, можно обронить "
    "короткую нуарную метафору вроде «неона в переулках Нео-Порта», но без "
    "ущерба точности ответа. Учитывай предыдущие реплики диалога, если они "
    "переданы."
)

SUMMARY_SYSTEM_PROMPT = (
    "Ты — модуль сжатия памяти диалога. Не отвечай пользователю. "
    "Возвращай только точную, компактную сводку без домыслов."
)

GEMINI_THINKING_LEVELS = ("minimal", "low", "high")


def _validate_bounded_int(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} должен быть целым числом")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} должен быть от {minimum} до {maximum}")


@dataclass(frozen=True)
class AgentConfig:
    """Неизменяемые настройки одной Agent Box."""

    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    max_output_tokens: int = 1_024
    max_history_messages: int = 1_000
    context_chars: int = 2_000_000
    max_input_chars: int = 1_000_000
    max_output_chars: int = 32_000
    thinking_level: str = "minimal"
    model: str | None = None
    force_overflow_api: bool = False
    compression_enabled: bool = True
    recent_messages: int = 6
    summary_batch_size: int = 10
    summary_max_output_tokens: int = 512

    def __post_init__(self) -> None:
        if not isinstance(self.system_prompt, str):
            raise TypeError("system_prompt должен быть строкой")
        if len(self.system_prompt) > 100_000:
            raise ValueError("system_prompt слишком длинный: максимум 100000 символов")
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
        ):
            raise TypeError("temperature должна быть числом")
        if not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("temperature должна быть от 0 до 2")
        if isinstance(self.top_p, bool) or not isinstance(self.top_p, (int, float)):
            raise TypeError("top_p должен быть числом")
        if not math.isfinite(self.top_p) or not 0 <= self.top_p <= 1:
            raise ValueError("top_p должен быть от 0 до 1")
        _validate_bounded_int("top_k", self.top_k, 1, 1_000)
        _validate_bounded_int("max_output_tokens", self.max_output_tokens, 1, 1_000_000)
        _validate_bounded_int("max_history_messages", self.max_history_messages, 2, 1_000)
        _validate_bounded_int("context_chars", self.context_chars, 1_000, 2_000_000)
        _validate_bounded_int("max_input_chars", self.max_input_chars, 1, 1_000_000)
        _validate_bounded_int("max_output_chars", self.max_output_chars, 1, 1_000_000)
        if not isinstance(self.thinking_level, str):
            raise TypeError("thinking_level должен быть строкой")
        if self.thinking_level not in GEMINI_THINKING_LEVELS:
            allowed = ", ".join(GEMINI_THINKING_LEVELS)
            raise ValueError(f"thinking_level должен быть одним из: {allowed}")
        if self.model is not None and not isinstance(self.model, str):
            raise TypeError("model должен быть строкой")
        if not isinstance(self.force_overflow_api, bool):
            raise TypeError("force_overflow_api должен быть bool")
        if not isinstance(self.compression_enabled, bool):
            raise TypeError("compression_enabled должен быть bool")
        _validate_bounded_int("recent_messages", self.recent_messages, 1, 1_000)
        _validate_bounded_int("summary_batch_size", self.summary_batch_size, 1, 1_000)
        _validate_bounded_int(
            "summary_max_output_tokens", self.summary_max_output_tokens, 1, 100_000
        )


@dataclass(frozen=True)
class TokenUsage:
    """Нормализованный provider usage; ``reported=False`` означает нет данных."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reported: bool = False
    reasoning_tokens: int = 0
    known_calls: int = 0
    unknown_calls: int = 0
    complete: bool = True

    def __post_init__(self) -> None:
        _validate_bounded_int("input_tokens", self.input_tokens, 0, 10**15)
        _validate_bounded_int("output_tokens", self.output_tokens, 0, 10**15)
        _validate_bounded_int("total_tokens", self.total_tokens, 0, 10**15)
        _validate_bounded_int("reasoning_tokens", self.reasoning_tokens, 0, 10**15)
        _validate_bounded_int("known_calls", self.known_calls, 0, 10**15)
        _validate_bounded_int("unknown_calls", self.unknown_calls, 0, 10**15)
        if not isinstance(self.reported, bool):
            raise TypeError("reported должен быть bool")
        if not isinstance(self.complete, bool):
            raise TypeError("complete должен быть bool")

    def __add__(self, other: object) -> TokenUsage:
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            reported=self.reported or other.reported,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            known_calls=self.known_calls + other.known_calls,
            unknown_calls=self.unknown_calls + other.unknown_calls,
            complete=self.complete and other.complete,
        )

    def as_session_delta(self) -> TokenUsage:
        if self.reported:
            return replace(self, known_calls=1, unknown_calls=0, complete=True)
        return TokenUsage(unknown_calls=1, complete=False)


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class ProviderReply:
    text: str
    provider: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    reasoning: str = ""


@dataclass(frozen=True)
class JudgeResult:
    passed: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("passed должен быть bool")
        if not isinstance(self.reason, str):
            raise TypeError("reason должен быть строкой")


@dataclass(frozen=True)
class AgentReply:
    text: str
    provider: str
    model: str
    attempts: tuple[dict, ...]
    usage: TokenUsage
    session_usage: TokenUsage
    token_metrics: dict
    turn_index: int
    status: str = "ok"
    judgement: JudgeResult | None = None
    reasoning: str = ""
    compression: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["attempts"] = list(self.attempts)
        return payload


class ProviderError(RuntimeError):
    """Ожидаемая ошибка провайдера, после которой можно попробовать следующий."""


class ProviderCancelledError(ProviderError):
    """Провайдер остановил текущий вызов по сигналу отмены."""


class ProviderContextLimitError(ProviderError):
    """Провайдер явно отклонил запрос из-за контекстного лимита."""


class OutputPolicyError(ProviderError):
    """Ответ провайдера не прошёл выходную политику Agent Box."""


class AgentUnavailableError(RuntimeError):
    def __init__(self, attempts: Sequence[dict]):
        super().__init__("Ни один LLM-провайдер сейчас не смог ответить")
        self.attempts = tuple(attempts)


class AgentCancelledError(RuntimeError):
    """Текущий вызов Agent Box отменён без изменения состояния сессии."""

    def __init__(self):
        super().__init__("Запрос отменён")


class AgentContextLimitError(RuntimeError):
    """Запрос не укладывается в локально известный или provider-контекст."""

    def __init__(self, message: str, *, token_metrics: dict, attempts: Sequence[dict] = ()):
        super().__init__(message)
        self.token_metrics = token_metrics
        self.attempts = tuple(attempts)


class InputPolicy(Protocol):
    def apply(self, user_text: object, config: AgentConfig) -> str: ...


class OutputPolicy(Protocol):
    def apply(self, output_text: object, config: AgentConfig) -> str: ...


class Judge(Protocol):
    def evaluate(
        self,
        messages: Sequence[Message],
        reply: ProviderReply,
        config: AgentConfig,
    ) -> JudgeResult: ...


@dataclass(frozen=True)
class DefaultInputPolicy:
    """Нормализует строку и отклоняет пустой или слишком длинный ввод."""

    def apply(self, user_text: object, config: AgentConfig) -> str:
        if user_text is None:
            raise ValueError("Введите сообщение")
        if not isinstance(user_text, str):
            raise TypeError("Сообщение должно быть строкой")
        text = user_text.strip()
        if not text:
            raise ValueError("Введите сообщение")
        if len(text) > config.max_input_chars:
            raise ValueError(
                f"Сообщение слишком длинное: максимум {config.max_input_chars} символов"
            )
        return text


@dataclass(frozen=True)
class DefaultOutputPolicy:
    """Нормализует ответ и отклоняет превышение лимита, не обрезая текст."""

    def apply(self, output_text: object, config: AgentConfig) -> str:
        if not isinstance(output_text, str):
            raise OutputPolicyError("LLM вернула ответ неверного типа")
        text = output_text.strip()
        if not text:
            raise OutputPolicyError("LLM вернула пустой ответ")
        if len(text) > config.max_output_chars:
            raise OutputPolicyError(
                f"Ответ слишком длинный: максимум {config.max_output_chars} символов"
            )
        return text


class LLMProvider(Protocol):
    id: str
    label: str
    default_model: str

    def available(self) -> bool: ...

    def generate(
        self,
        messages: Sequence[Message],
        config: AgentConfig,
        cancel_event: threading.Event,
    ) -> ProviderReply: ...


class HistoryStore(Protocol):
    def load(self, session_id: str, limit: int | None = None) -> list[tuple[str, str]]: ...

    def append(self, session_id: str, role: str, content: str) -> None: ...

    def clear(self, session_id: str) -> None: ...

    def next_turn_index(self, session_id: str) -> int: ...

    def load_request_logs(self, session_id: str) -> list[dict]: ...

    def load_summary(self, session_id: str) -> dict | None: ...

    def save_summary(
        self,
        session_id: str,
        *,
        content: str,
        summarized_message_count: int,
        revision: int,
        usage: dict,
    ) -> None: ...

    def append_exchange_with_log(
        self,
        *,
        session_id: str,
        request_id: str,
        turn_index: int,
        user_text: str,
        assistant_text: str,
        provider: str,
        model: str,
        status: str,
        metrics: dict,
        usage: dict,
        attempts: list[dict],
        error: str | None = None,
    ) -> None: ...

    def append_log(
        self,
        *,
        request_id: str,
        session_id: str,
        turn_index: int,
        provider: str | None,
        model: str | None,
        status: str,
        metrics: dict,
        usage: dict,
        attempts: list[dict],
        error: str | None = None,
    ) -> None: ...


class ChatAgent:
    """Инкапсулирует конфиг, политики, историю, fallback, judge и usage."""

    def __init__(
        self,
        providers: Sequence[LLMProvider],
        config: AgentConfig | None = None,
        input_policy: InputPolicy | None = None,
        output_policy: OutputPolicy | None = None,
        judge: Judge | None = None,
        history_store: HistoryStore | None = None,
        session_id: str = "default",
    ):
        if not providers:
            raise ValueError("Агенту нужен хотя бы один LLM-провайдер")
        self._providers = tuple(providers)
        self._config = config or AgentConfig()
        self._input_policy = input_policy or DefaultInputPolicy()
        self._output_policy = output_policy or DefaultOutputPolicy()
        self._judge = judge
        self._history_store = history_store
        self._session_id = session_id
        self._history: list[Message] = (
            [Message(role, content) for role, content in history_store.load(
                session_id, limit=None
            )]
            if history_store is not None
            else []
        )
        raw_summary = (
            history_store.load_summary(session_id)
            if history_store is not None and hasattr(history_store, "load_summary")
            else None
        )
        self._summary_state = SummaryState(
            content=str((raw_summary or {}).get("content") or ""),
            summarized_message_count=int(
                (raw_summary or {}).get("summarized_message_count") or 0
            ),
            revision=int((raw_summary or {}).get("revision") or 0),
            usage=dict((raw_summary or {}).get("usage") or {}),
        )
        self._model_config = load_model_config(Path(__file__).resolve().with_name("model_config.json"))
        self._session_usage = self._restore_session_usage()
        self._lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active_cancel_event: threading.Event | None = None

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def history(self) -> tuple[Message, ...]:
        with self._lock:
            return tuple(self._history)

    @property
    def session_usage(self) -> TokenUsage:
        with self._lock:
            return self._session_usage

    @property
    def summary(self) -> SummaryState:
        with self._lock:
            return self._summary_state

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._summary_state = SummaryState()
            self._session_usage = TokenUsage()
            if self._history_store is not None:
                self._history_store.clear(self._session_id)

    def cancel(self) -> bool:
        """Сигнализирует активному вызову об отмене, не ожидая history lock."""
        with self._active_lock:
            cancel_event = self._active_cancel_event
            if cancel_event is None:
                return False
            cancel_event.set()
            return True

    @staticmethod
    def _trim_to_context(messages: list[Message], budget: int) -> list[Message]:
        """Keeps the newest messages within a character budget, always keeping
        at least the last one (the current user turn)."""
        if not messages:
            return messages
        total = len(messages[-1].content)
        cut = len(messages) - 1
        for i in range(len(messages) - 2, -1, -1):
            total += len(messages[i].content)
            if total > budget:
                break
            cut = i
        return messages[cut:]

    def _restore_session_usage(self) -> TokenUsage:
        if self._history_store is None or not hasattr(self._history_store, "load_request_logs"):
            return TokenUsage()
        usage = TokenUsage()
        for row in self._history_store.load_request_logs(self._session_id):
            raw = row.get("usage") or {}
            if not isinstance(raw, dict):
                continue
            try:
                current = TokenUsage(
                    input_tokens=int(raw.get("input_tokens") or 0),
                    output_tokens=int(raw.get("output_tokens") or 0),
                    total_tokens=int(raw.get("total_tokens") or 0),
                    reported=bool(raw.get("reported")),
                    reasoning_tokens=int(raw.get("reasoning_tokens") or 0),
                )
            except (TypeError, ValueError):
                current = TokenUsage()
            usage = usage + current.as_session_delta()
        return usage

    def request_log(self) -> list[dict]:
        if self._history_store is None or not hasattr(self._history_store, "load_request_logs"):
            return []
        return self._history_store.load_request_logs(self._session_id)

    def _next_turn_index(self) -> int:
        if self._history_store is not None and hasattr(self._history_store, "next_turn_index"):
            return self._history_store.next_turn_index(self._session_id)
        return len(self._history) // 2 + 1

    def _provider_model(self, provider: LLMProvider, config: AgentConfig) -> str:
        if config.model and hasattr(provider, "model_options"):
            options = provider.model_options()  # type: ignore[attr-defined]
            if config.model in options:
                return config.model
        return provider.default_model

    @staticmethod
    def _compression_config(config: AgentConfig) -> CompressionConfig:
        return CompressionConfig(
            enabled=config.compression_enabled,
            recent_messages=config.recent_messages,
            batch_size=config.summary_batch_size,
        )

    def _save_summary(self, state: SummaryState) -> None:
        self._summary_state = state
        if self._history_store is not None and hasattr(self._history_store, "save_summary"):
            self._history_store.save_summary(
                self._session_id,
                content=state.content,
                summarized_message_count=state.summarized_message_count,
                revision=state.revision,
                usage=state.usage,
            )

    def _compression_metrics(
        self,
        *,
        manager: ContextManager,
        effective_history: Sequence[Message],
        model: str,
        summary_calls: list[dict],
        status: str,
    ) -> dict:
        full_tokens = count_text(history_text(self._history), model=model).to_dict()
        effective_tokens = count_text(history_text(effective_history), model=model).to_dict()
        summary_tokens = count_text(manager.state.content, model=model).to_dict()
        return {
            "enabled": manager.config.enabled,
            "status": status,
            "recent_messages_limit": manager.config.recent_messages,
            "batch_size": manager.config.batch_size,
            "raw_message_count": len(self._history),
            "summarized_message_count": manager.state.summarized_message_count,
            "verbatim_message_count": min(
                len(self._history),
                max(
                    manager.config.recent_messages,
                    len(self._history) - manager.state.summarized_message_count,
                ),
            ),
            "summary_revision": manager.state.revision,
            "summary_text": manager.state.content,
            "full_history_tokens": full_tokens,
            "effective_history_tokens": effective_tokens,
            "summary_tokens": summary_tokens,
            "estimated_tokens_saved_this_request": max(
                0, full_tokens["value"] - effective_tokens["value"]
            ),
            "summary_calls_this_turn": summary_calls,
        }

    def _context_window(self, provider_id: str, model: str) -> int | None:
        providers = self._model_config.get("providers", {})
        if not isinstance(providers, dict):
            return None
        provider_config = providers.get(provider_id, {})
        if not isinstance(provider_config, dict):
            return None
        models = provider_config.get("models", {})
        if not isinstance(models, dict):
            return None
        model_config = models.get(model, {})
        if not isinstance(model_config, dict):
            return None
        value = model_config.get("context_window_tokens")
        return value if isinstance(value, int) and value > 0 else None

    def _prepared_prompt(self, provider: LLMProvider, messages: Sequence[Message], config: AgentConfig) -> str:
        if hasattr(provider, "prepare_prompt"):
            return provider.prepare_prompt(messages, config)  # type: ignore[attr-defined]
        labels = {"user": "Пользователь", "assistant": "Ассистент"}
        transcript = "\n".join(
            f"{labels.get(message.role, message.role)}: {message.content}"
            for message in messages
        )
        return f"Продолжи диалог.\n\n{transcript}\nАссистент:"

    @staticmethod
    def _usage_dict(usage: TokenUsage) -> dict:
        return asdict(usage)

    def _log_attempt(
        self,
        *,
        request_id: str,
        turn_index: int,
        provider: str | None,
        model: str | None,
        status: str,
        metrics: dict,
        usage: TokenUsage | None,
        attempts: list[dict],
        error: str | None,
    ) -> None:
        if self._history_store is None or not hasattr(self._history_store, "append_log"):
            return
        self._history_store.append_log(
            request_id=request_id,
            session_id=self._session_id,
            turn_index=turn_index,
            provider=provider,
            model=model,
            status=status,
            metrics=metrics,
            usage=self._usage_dict(usage or TokenUsage()),
            attempts=attempts,
            error=error,
        )

    def _refresh_compression(
        self,
        *,
        manager: ContextManager,
        provider: LLMProvider,
        config: AgentConfig,
        cancel_event: threading.Event,
        request_id: str,
        turn_index: int,
    ) -> tuple[list[dict], str]:
        """Create and persist every ready summary revision before the answer."""
        events: list[dict] = []
        if not manager.config.enabled:
            return events, "disabled"

        while True:
            batch = manager.ready_batch(self._history)
            if not batch:
                return events, "compressed" if events else "up_to_date"
            if cancel_event.is_set():
                raise AgentCancelledError()
            prompt = render_summary_prompt(manager.state.content, batch)
            summary_config = replace(
                config,
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                max_output_tokens=config.summary_max_output_tokens,
                compression_enabled=False,
            )
            summary_messages = [Message("user", prompt)]
            prepared = self._prepared_prompt(provider, summary_messages, summary_config)
            model = self._provider_model(provider, summary_config)
            metrics = build_snapshot(
                current_message=prompt,
                history_before=(),
                prepared_prompt=prepared,
                system_prompt=summary_config.system_prompt,
                model=model,
                max_output_tokens=summary_config.max_output_tokens,
                context_window_tokens=self._context_window(provider.id, model),
            ).to_dict()
            summary_request_id = f"{request_id}-summary-{manager.state.revision + 1}"
            try:
                generated = provider.generate(summary_messages, summary_config, cancel_event)
                summary_text = self._output_policy.apply(generated.text, summary_config)
            except ProviderCancelledError:
                raise AgentCancelledError() from None
            except ProviderError as exc:
                events.append(
                    {
                        "status": "failed",
                        "message_count": len(batch),
                        "error": type(exc).__name__,
                    }
                )
                self._log_attempt(
                    request_id=summary_request_id,
                    turn_index=turn_index,
                    provider=provider.id,
                    model=model,
                    status="summary_failed",
                    metrics=metrics,
                    usage=TokenUsage(),
                    attempts=[],
                    error=str(exc),
                )
                return events, "summary_failed"

            state = manager.advance(
                summary_text, len(batch), self._usage_dict(generated.usage)
            )
            self._save_summary(state)
            self._session_usage = (
                self._session_usage + generated.usage.as_session_delta()
            )
            event = {
                "status": "ok",
                "revision": state.revision,
                "message_count": len(batch),
                "summarized_message_count": state.summarized_message_count,
                "usage": self._usage_dict(generated.usage),
            }
            events.append(event)
            self._log_attempt(
                request_id=summary_request_id,
                turn_index=turn_index,
                provider=generated.provider,
                model=generated.model,
                status="summary_ok",
                metrics=metrics,
                usage=generated.usage,
                attempts=[{"provider": provider.id, "status": "ok"}],
                error=None,
            )

    def ask(
        self,
        user_text: str,
        *,
        provider_id: str | None = None,
        **config_overrides: object,
    ) -> AgentReply:
        text = self._input_policy.apply(user_text, self._config)
        overrides = {k: v for k, v in config_overrides.items() if v is not None}
        config = replace(self._config, **overrides) if overrides else self._config
        providers = self._providers
        if provider_id is not None:
            providers = tuple(p for p in providers if p.id == provider_id)
            if not providers:
                raise ValueError(f"Неизвестный провайдер: {provider_id}")

        with self._lock:
            cancel_event = threading.Event()
            with self._active_lock:
                self._active_cancel_event = cancel_event
            try:
                attempts: list[dict] = []
                request_id = uuid4().hex
                turn_index = self._next_turn_index()
                manager = ContextManager(
                    self._compression_config(config), self._summary_state
                )

                for provider in providers:
                    if cancel_event.is_set():
                        raise AgentCancelledError()
                    if not provider.available():
                        attempts.append({"provider": provider.id, "status": "skipped"})
                        continue
                    if cancel_event.is_set():
                        raise AgentCancelledError()
                    model_for_metrics = self._provider_model(provider, config)
                    summary_calls, compression_status = self._refresh_compression(
                        manager=manager,
                        provider=provider,
                        config=config,
                        cancel_event=cancel_event,
                        request_id=request_id,
                        turn_index=turn_index,
                    )
                    context_view = manager.build(self._history, Message)
                    effective_history = list(context_view.messages)
                    request_messages = [*effective_history, Message("user", text)]
                    prepared_prompt = self._prepared_prompt(provider, request_messages, config)
                    snapshot = build_snapshot(
                        current_message=text,
                        history_before=effective_history,
                        prepared_prompt=prepared_prompt,
                        system_prompt=config.system_prompt,
                        model=model_for_metrics,
                        max_output_tokens=config.max_output_tokens,
                        context_window_tokens=self._context_window(provider.id, model_for_metrics),
                    )
                    metrics = snapshot.to_dict()
                    compression = self._compression_metrics(
                        manager=manager,
                        effective_history=effective_history,
                        model=model_for_metrics,
                        summary_calls=summary_calls,
                        status=compression_status,
                    )
                    metrics["compression"] = compression
                    budget = metrics["context_budget"]
                    if (
                        budget.get("status") == "local_context_limit"
                        and not config.force_overflow_api
                    ):
                        attempts.append(
                            {
                                "provider": provider.id,
                                "status": "local_context_limit",
                                "model": model_for_metrics,
                            }
                        )
                        self._log_attempt(
                            request_id=request_id,
                            turn_index=turn_index,
                            provider=provider.id,
                            model=model_for_metrics,
                            status="local_context_limit",
                            metrics=metrics,
                            usage=TokenUsage(),
                            attempts=attempts,
                            error="Локальная проверка: запрос превышает известный контекстный лимит",
                        )
                        raise AgentContextLimitError(
                            "Запрос превышает известный контекстный лимит модели",
                            token_metrics=metrics,
                            attempts=attempts,
                        )
                    try:
                        generated = provider.generate(
                            request_messages, config, cancel_event
                        )
                        if cancel_event.is_set():
                            raise AgentCancelledError()
                        answer = self._output_policy.apply(generated.text, config)
                    except ProviderCancelledError:
                        raise AgentCancelledError() from None
                    except ProviderContextLimitError as exc:
                        if cancel_event.is_set():
                            raise AgentCancelledError() from None
                        attempts.append(
                            {
                                "provider": provider.id,
                                "status": "provider_context_limit",
                                "error": type(exc).__name__,
                                "model": model_for_metrics,
                            }
                        )
                        self._log_attempt(
                            request_id=request_id,
                            turn_index=turn_index,
                            provider=provider.id,
                            model=model_for_metrics,
                            status="provider_context_limit",
                            metrics=metrics,
                            usage=TokenUsage(),
                            attempts=attempts,
                            error=str(exc),
                        )
                        raise AgentContextLimitError(
                            "Провайдер отклонил запрос из-за контекстного лимита",
                            token_metrics=metrics,
                            attempts=attempts,
                        ) from None
                    except ProviderError as exc:
                        if cancel_event.is_set():
                            raise AgentCancelledError() from None
                        attempts.append(
                            {
                                "provider": provider.id,
                                "status": "failed",
                                "error": type(exc).__name__,
                            }
                        )
                        continue

                    judgement = None
                    if self._judge is not None:
                        judgement = self._judge.evaluate(
                            request_messages, generated, config
                        )
                        if not isinstance(judgement, JudgeResult):
                            raise TypeError("Judge должен вернуть JudgeResult")
                    with self._active_lock:
                        if cancel_event.is_set():
                            raise AgentCancelledError()
                        if self._active_cancel_event is cancel_event:
                            self._active_cancel_event = None

                    attempts.append({"provider": provider.id, "status": "ok"})
                    history_after = [
                        *self._history,
                        Message("user", text),
                        Message("assistant", answer),
                    ]
                    metrics = build_snapshot(
                        current_message=text,
                        history_before=effective_history,
                        prepared_prompt=prepared_prompt,
                        system_prompt=config.system_prompt,
                        model=generated.model,
                        max_output_tokens=config.max_output_tokens,
                        context_window_tokens=self._context_window(provider.id, generated.model),
                        visible_answer=answer,
                        history_after=[
                            *effective_history,
                            Message("user", text),
                            Message("assistant", answer),
                        ],
                    ).to_dict()
                    compression = self._compression_metrics(
                        manager=manager,
                        effective_history=effective_history,
                        model=generated.model,
                        summary_calls=summary_calls,
                        status=compression_status,
                    )
                    compression["raw_message_count_after"] = len(history_after)
                    compression["full_history_tokens_after"] = count_text(
                        history_text(history_after), model=generated.model
                    ).to_dict()
                    metrics["compression"] = compression
                    session_usage = self._session_usage + generated.usage.as_session_delta()
                    self._history.extend(
                        (Message("user", text), Message("assistant", answer))
                    )
                    self._session_usage = session_usage
                    if self._history_store is not None:
                        if hasattr(self._history_store, "append_exchange_with_log"):
                            self._history_store.append_exchange_with_log(
                                session_id=self._session_id,
                                request_id=request_id,
                                turn_index=turn_index,
                                user_text=text,
                                assistant_text=answer,
                                provider=generated.provider,
                                model=generated.model,
                                status="ok",
                                metrics=metrics,
                                usage=self._usage_dict(generated.usage),
                                attempts=attempts,
                            )
                        else:
                            self._history_store.append(self._session_id, "user", text)
                            self._history_store.append(
                                self._session_id, "assistant", answer
                            )
                    return AgentReply(
                        text=answer,
                        provider=generated.provider,
                        model=generated.model,
                        attempts=tuple(attempts),
                        usage=generated.usage,
                        session_usage=session_usage,
                        token_metrics=metrics,
                        turn_index=turn_index,
                        status="ok",
                        judgement=judgement,
                        reasoning=generated.reasoning,
                        compression=compression,
                    )

                self._log_attempt(
                    request_id=request_id,
                    turn_index=turn_index,
                    provider=None,
                    model=None,
                    status="unavailable",
                    metrics={},
                    usage=TokenUsage(),
                    attempts=attempts,
                    error="Ни один LLM-провайдер сейчас не смог ответить",
                )
                raise AgentUnavailableError(attempts)
            finally:
                with self._active_lock:
                    if self._active_cancel_event is cancel_event:
                        self._active_cancel_event = None


class AgentStore:
    """Создаёт независимого агента на каждую web-сессию."""

    def __init__(self, factory: Callable[[str], ChatAgent], max_sessions: int = 100):
        self._factory = factory
        self._max_sessions = max_sessions
        self._agents: dict[str, ChatAgent] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> ChatAgent:
        normalized = (session_id or "default")[:80]
        with self._lock:
            if normalized not in self._agents:
                if len(self._agents) >= self._max_sessions:
                    oldest = next(iter(self._agents))
                    del self._agents[oldest]
                self._agents[normalized] = self._factory(normalized)
            return self._agents[normalized]

    def reset(self, session_id: str) -> None:
        self.get(session_id).reset()

    def cancel(self, session_id: str) -> bool:
        normalized = (session_id or "default")[:80]
        with self._lock:
            agent = self._agents.get(normalized)
        return agent.cancel() if agent is not None else False
