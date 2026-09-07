"""Изолированная Agent Box для Day 6.

Интерфейсы (web/CLI) знают только про :meth:`ChatAgent.ask`. Конфигурация,
политики, история, fallback, judge и учёт токенов остаются внутри агента.
"""

from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Protocol, Sequence


DEFAULT_SYSTEM_PROMPT = (
    "Ты полезный русскоязычный чат-агент. Отвечай ясно и по существу. "
    "Учитывай предыдущие реплики диалога, если они переданы."
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
    max_output_tokens: int = 1_024
    max_history_messages: int = 12
    max_input_chars: int = 8_000
    max_output_chars: int = 32_000
    thinking_level: str = "minimal"

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
        _validate_bounded_int("max_output_tokens", self.max_output_tokens, 1, 1_000_000)
        _validate_bounded_int("max_history_messages", self.max_history_messages, 2, 1_000)
        _validate_bounded_int("max_input_chars", self.max_input_chars, 1, 1_000_000)
        _validate_bounded_int("max_output_chars", self.max_output_chars, 1, 1_000_000)
        if not isinstance(self.thinking_level, str):
            raise TypeError("thinking_level должен быть строкой")
        if self.thinking_level not in GEMINI_THINKING_LEVELS:
            allowed = ", ".join(GEMINI_THINKING_LEVELS)
            raise ValueError(f"thinking_level должен быть одним из: {allowed}")


@dataclass(frozen=True)
class TokenUsage:
    """Нормализованный provider usage; ``reported=False`` означает нет данных."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reported: bool = False
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        _validate_bounded_int("input_tokens", self.input_tokens, 0, 10**15)
        _validate_bounded_int("output_tokens", self.output_tokens, 0, 10**15)
        _validate_bounded_int("total_tokens", self.total_tokens, 0, 10**15)
        _validate_bounded_int("reasoning_tokens", self.reasoning_tokens, 0, 10**15)
        if not isinstance(self.reported, bool):
            raise TypeError("reported должен быть bool")

    def __add__(self, other: object) -> TokenUsage:
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            reported=self.reported or other.reported,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


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
    judgement: JudgeResult | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["attempts"] = list(self.attempts)
        return payload


class ProviderError(RuntimeError):
    """Ожидаемая ошибка провайдера, после которой можно попробовать следующий."""


class ProviderCancelledError(ProviderError):
    """Провайдер остановил текущий вызов по сигналу отмены."""


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


class ChatAgent:
    """Инкапсулирует конфиг, политики, историю, fallback, judge и usage."""

    def __init__(
        self,
        providers: Sequence[LLMProvider],
        config: AgentConfig | None = None,
        input_policy: InputPolicy | None = None,
        output_policy: OutputPolicy | None = None,
        judge: Judge | None = None,
    ):
        if not providers:
            raise ValueError("Агенту нужен хотя бы один LLM-провайдер")
        self._providers = tuple(providers)
        self._config = config or AgentConfig()
        self._input_policy = input_policy or DefaultInputPolicy()
        self._output_policy = output_policy or DefaultOutputPolicy()
        self._judge = judge
        self._history: list[Message] = []
        self._session_usage = TokenUsage()
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

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._session_usage = TokenUsage()

    def cancel(self) -> bool:
        """Сигнализирует активному вызову об отмене, не ожидая history lock."""
        with self._active_lock:
            cancel_event = self._active_cancel_event
            if cancel_event is None:
                return False
            cancel_event.set()
            return True

    def ask(
        self,
        user_text: str,
        *,
        provider_id: str | None = None,
        thinking_level: str | None = None,
    ) -> AgentReply:
        text = self._input_policy.apply(user_text, self._config)
        config = self._config if thinking_level is None else replace(
            self._config, thinking_level=thinking_level
        )
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
                request_messages = [*self._history, Message("user", text)]
                attempts: list[dict] = []

                for provider in providers:
                    if cancel_event.is_set():
                        raise AgentCancelledError()
                    if not provider.available():
                        attempts.append({"provider": provider.id, "status": "skipped"})
                        continue
                    if cancel_event.is_set():
                        raise AgentCancelledError()
                    try:
                        generated = provider.generate(
                            request_messages, config, cancel_event
                        )
                        if cancel_event.is_set():
                            raise AgentCancelledError()
                        answer = self._output_policy.apply(generated.text, config)
                    except ProviderCancelledError:
                        raise AgentCancelledError() from None
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
                    session_usage = self._session_usage + generated.usage
                    self._history.extend(
                        (Message("user", text), Message("assistant", answer))
                    )
                    self._history = self._history[-config.max_history_messages :]
                    self._session_usage = session_usage
                    return AgentReply(
                        text=answer,
                        provider=generated.provider,
                        model=generated.model,
                        attempts=tuple(attempts),
                        usage=generated.usage,
                        session_usage=session_usage,
                        judgement=judgement,
                    )

                raise AgentUnavailableError(attempts)
            finally:
                with self._active_lock:
                    if self._active_cancel_event is cancel_event:
                        self._active_cancel_event = None


class AgentStore:
    """Создаёт независимого агента на каждую web-сессию."""

    def __init__(self, factory: Callable[[], ChatAgent], max_sessions: int = 100):
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
                self._agents[normalized] = self._factory()
            return self._agents[normalized]

    def reset(self, session_id: str) -> None:
        self.get(session_id).reset()

    def cancel(self, session_id: str) -> bool:
        normalized = (session_id or "default")[:80]
        with self._lock:
            agent = self._agents.get(normalized)
        return agent.cancel() if agent is not None else False
