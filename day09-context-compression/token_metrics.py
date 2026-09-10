"""Token accounting helpers for Day 9.

Local counts are estimates: the chosen DeepSeek endpoint reports authoritative
usage only after a successful API call. The UI marks these local counts with
``≈`` and keeps them separate from provider usage.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


TOKENIZER_ID = "unicode-segment-estimate-v1"
COUNT_SOURCE = "local_unicode_segment_estimate"
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_]+|[А-Яа-яЁё]+|[^\s]", re.UNICODE)


@dataclass(frozen=True)
class TokenCount:
    value: int
    count_source: str = COUNT_SOURCE
    is_estimate: bool = True
    tokenizer: str = TOKENIZER_ID
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ContextBudget:
    request_tokens: int
    response_reserve_tokens: int
    context_window_tokens: int | None
    available_for_request_tokens: int | None
    overflow_tokens: int
    fits: bool | None
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TokenSnapshot:
    current_message_tokens: TokenCount
    history_tokens_before: TokenCount
    request_tokens_before_send: TokenCount
    visible_answer_tokens: TokenCount | None
    history_tokens_after: TokenCount | None
    context_budget: ContextBudget

    def to_dict(self) -> dict:
        payload = asdict(self)
        if self.visible_answer_tokens is not None:
            payload["visible_answer_tokens"] = self.visible_answer_tokens.to_dict()
        if self.history_tokens_after is not None:
            payload["history_tokens_after"] = self.history_tokens_after.to_dict()
        return payload


def load_model_config(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def estimate_tokens(text: str) -> int:
    """A deterministic, language-aware approximation.

    It intentionally does not claim provider-tokenizer accuracy. Long word-like
    chunks contribute extra pieces, while punctuation and non-space symbols count
    as one segment each.
    """
    if not text:
        return 0
    total = 0
    for segment in _SEGMENT_RE.findall(text):
        if re.fullmatch(r"[A-Za-z0-9_]+|[А-Яа-яЁё]+", segment, re.UNICODE):
            total += max(1, (len(segment) + 5) // 6)
        else:
            total += 1
    return total


def count_text(text: str, *, model: str) -> TokenCount:
    return TokenCount(value=estimate_tokens(text), model=model)


def history_text(messages: Sequence[object]) -> str:
    labels = {"user": "Пользователь", "assistant": "Ассистент"}
    rows = []
    for message in messages:
        role = getattr(message, "role", "")
        content = getattr(message, "content", "")
        rows.append(f"{labels.get(role, role)}: {content}")
    return "\n".join(rows)


def provider_request_text(system_prompt: str, prepared_prompt: str) -> str:
    if system_prompt:
        return f"system: {system_prompt}\n\nuser: {prepared_prompt}"
    return f"user: {prepared_prompt}"


def context_budget(
    request_tokens: int,
    *,
    max_output_tokens: int,
    context_window_tokens: int | None,
) -> ContextBudget:
    if context_window_tokens is None:
        return ContextBudget(
            request_tokens=request_tokens,
            response_reserve_tokens=max_output_tokens,
            context_window_tokens=None,
            available_for_request_tokens=None,
            overflow_tokens=0,
            fits=None,
            status="unknown_context_limit",
        )
    available = max(0, context_window_tokens - max_output_tokens)
    overflow = max(0, request_tokens - available)
    return ContextBudget(
        request_tokens=request_tokens,
        response_reserve_tokens=max_output_tokens,
        context_window_tokens=context_window_tokens,
        available_for_request_tokens=available,
        overflow_tokens=overflow,
        fits=overflow == 0,
        status="ok" if overflow == 0 else "local_context_limit",
    )


def build_snapshot(
    *,
    current_message: str,
    history_before: Sequence[object],
    prepared_prompt: str,
    system_prompt: str,
    model: str,
    max_output_tokens: int,
    context_window_tokens: int | None,
    visible_answer: str | None = None,
    history_after: Sequence[object] | None = None,
) -> TokenSnapshot:
    request_count = count_text(
        provider_request_text(system_prompt, prepared_prompt), model=model
    )
    answer_count = (
        count_text(visible_answer, model=model) if visible_answer is not None else None
    )
    history_after_count = (
        count_text(history_text(history_after), model=model)
        if history_after is not None
        else None
    )
    return TokenSnapshot(
        current_message_tokens=count_text(current_message, model=model),
        history_tokens_before=count_text(history_text(history_before), model=model),
        request_tokens_before_send=request_count,
        visible_answer_tokens=answer_count,
        history_tokens_after=history_after_count,
        context_budget=context_budget(
            request_count.value,
            max_output_tokens=max_output_tokens,
            context_window_tokens=context_window_tokens,
        ),
    )
