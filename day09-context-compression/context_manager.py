"""Pure context-window planning for Day 9.

The full transcript remains the source of truth.  This module only decides
which old messages are ready for summarisation and builds the smaller view
that is sent to an LLM.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Sequence


SUMMARY_PREFIX = (
    "Сводка предыдущей части диалога. Считай её надёжной памятью, но при "
    "противоречии предпочитай более свежие дословные сообщения:\n"
)


@dataclass(frozen=True)
class SummaryState:
    content: str = ""
    summarized_message_count: int = 0
    revision: int = 0
    usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompressionConfig:
    enabled: bool = True
    recent_messages: int = 6
    batch_size: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("compression_enabled должен быть bool")
        for name, value in (
            ("recent_messages", self.recent_messages),
            ("summary_batch_size", self.batch_size),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} должен быть целым числом")
            if value < 1 or value > 1_000:
                raise ValueError(f"{name} должен быть от 1 до 1000")


@dataclass(frozen=True)
class ContextView:
    messages: tuple
    summary: SummaryState
    raw_message_count: int
    verbatim_message_count: int
    pending_old_messages: int

    def metadata(self) -> dict:
        return {
            "enabled": True,
            "summary": self.summary.to_dict(),
            "raw_message_count": self.raw_message_count,
            "verbatim_message_count": self.verbatim_message_count,
            "pending_old_messages": self.pending_old_messages,
        }


class ContextManager:
    """Creates rolling summaries in fixed-size message batches."""

    def __init__(self, config: CompressionConfig, state: SummaryState | None = None):
        self.config = config
        self.state = state or SummaryState()

    def ready_batch(self, history: Sequence) -> tuple:
        """Return exactly one batch while always protecting the newest N."""
        if not self.config.enabled:
            return ()
        safe_end = max(0, len(history) - self.config.recent_messages)
        start = min(self.state.summarized_message_count, safe_end)
        if safe_end - start < self.config.batch_size:
            return ()
        return tuple(history[start : start + self.config.batch_size])

    def advance(self, content: str, batch_size: int, usage: dict | None = None) -> SummaryState:
        text = str(content).strip()
        if not text:
            raise ValueError("Суммаризатор вернул пустую сводку")
        if batch_size != self.config.batch_size:
            raise ValueError("Размер обработанного пакета не совпадает с настройкой")
        self.state = SummaryState(
            content=text,
            summarized_message_count=self.state.summarized_message_count + batch_size,
            revision=self.state.revision + 1,
            usage=dict(usage or {}),
        )
        return self.state

    def refresh(self, history: Sequence, summarize: Callable[[str, Sequence], tuple[str, dict]]) -> list[SummaryState]:
        """Compress every currently ready batch and return created revisions."""
        revisions = []
        while True:
            batch = self.ready_batch(history)
            if not batch:
                return revisions
            content, usage = summarize(self.state.content, batch)
            revisions.append(self.advance(content, len(batch), usage))

    def build(self, history: Sequence, message_factory: Callable[[str, str], object]) -> ContextView:
        if not self.config.enabled:
            return ContextView(
                messages=tuple(history),
                summary=SummaryState(),
                raw_message_count=len(history),
                verbatim_message_count=len(history),
                pending_old_messages=0,
            )

        # If N is increased at runtime, re-include enough raw messages to keep
        # the newly requested tail verbatim. The full transcript makes this
        # reversible even though those messages also exist in the summary.
        latest_allowed_start = max(0, len(history) - self.config.recent_messages)
        start = min(self.state.summarized_message_count, latest_allowed_start)
        tail = tuple(history[start:])
        messages = tail
        if self.state.content:
            messages = (
                message_factory("system", SUMMARY_PREFIX + self.state.content),
                *tail,
            )
        pending = max(0, len(tail) - self.config.recent_messages)
        return ContextView(
            messages=messages,
            summary=self.state,
            raw_message_count=len(history),
            verbatim_message_count=len(tail),
            pending_old_messages=pending,
        )


def render_summary_prompt(previous_summary: str, batch: Sequence) -> str:
    labels = {"user": "Пользователь", "assistant": "Ассистент", "system": "Система"}
    transcript = "\n".join(
        f"{labels.get(getattr(item, 'role', ''), getattr(item, 'role', ''))}: "
        f"{getattr(item, 'content', '')}"
        for item in batch
    )
    previous = previous_summary.strip() or "(пока нет)"
    return (
        "Обнови сводку диалога. Сохрани имена, числа, решения, предпочтения, "
        "обещания, открытые вопросы и причинно-следственные связи. Не добавляй "
        "фактов и не отвечай участникам. Верни только компактную сводку.\n\n"
        f"Предыдущая сводка:\n{previous}\n\nНовый пакет сообщений:\n{transcript}"
    )
