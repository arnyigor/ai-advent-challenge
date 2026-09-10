"""CLI for Day 9: rolling context summary plus token comparison."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DAY_DIR = Path(__file__).resolve().parent
for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent import (
    GEMINI_THINKING_LEVELS,
    AgentCancelledError,
    AgentContextLimitError,
    AgentUnavailableError,
    ChatAgent,
    TokenUsage,
)
from history_store import SQLiteHistoryStore
from providers import create_default_providers


def build_agent(session_id: str = "cli") -> ChatAgent:
    store = SQLiteHistoryStore(DAY_DIR / "chat_history.db")
    return ChatAgent(create_default_providers(), history_store=store, session_id=session_id)


def main() -> int:
    provider_ids = [provider.id for provider in create_default_providers()]
    parser = argparse.ArgumentParser(description="Day 9 — сжатие истории")
    parser.add_argument("message", nargs="*", help="один вопрос; без аргумента — чат")
    parser.add_argument(
        "--provider", choices=provider_ids, default=None,
        help="принудительно использовать один провайдер вместо fallback-цепочки",
    )
    parser.add_argument(
        "--thinking", choices=GEMINI_THINKING_LEVELS, default=None,
        help="уровень reasoning для этого запуска",
    )
    parser.add_argument(
        "--session", default="cli",
        help="имя сессии — история каждой сессии хранится и восстанавливается отдельно",
    )
    parser.add_argument(
        "--no-compression", action="store_true",
        help="контрольный режим: отправлять полную историю",
    )
    parser.add_argument("--recent", type=int, default=6, help="последние N сообщений дословно")
    parser.add_argument("--batch", type=int, default=10, help="размер пакета для summary")
    args = parser.parse_args()
    agent = build_agent(args.session)

    if args.message:
        return ask_and_print(
            agent,
            " ".join(args.message),
            args.provider,
            args.thinking,
            compression_enabled=not args.no_compression,
            recent_messages=args.recent,
            summary_batch_size=args.batch,
        )

    provider = args.provider
    thinking = args.thinking or agent.config.thinking_level
    restored = len(agent.history) // 2
    print(
        "Day 9 · Сжатие истории · /reset — очистить историю · /exit — выход\n"
        f"сессия: {args.session} · восстановлено реплик: {restored} · "
        f"провайдер: {provider or 'авто'} · reasoning: {thinking} · "
        f"/provider <id|авто> · /thinking <{'|'.join(GEMINI_THINKING_LEVELS)}>"
    )
    while True:
        try:
            message = input("\nВы> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if message in {"/exit", "/quit"}:
            return 0
        if message == "/reset":
            agent.reset()
            print("Агент> История и счётчики токенов очищены.")
            continue
        if message.startswith("/provider"):
            value = message.removeprefix("/provider").strip()
            provider = None if value in {"", "авто", "auto"} else value
            print(f"Агент> Провайдер: {provider or 'авто'}")
            continue
        if message.startswith("/thinking"):
            value = message.removeprefix("/thinking").strip()
            if value not in GEMINI_THINKING_LEVELS:
                print(f"Агент> Допустимо: {', '.join(GEMINI_THINKING_LEVELS)}")
                continue
            thinking = value
            print(f"Агент> Reasoning: {thinking}")
            continue
        if not message:
            continue
        ask_and_print(
            agent,
            message,
            provider,
            thinking,
            compression_enabled=not args.no_compression,
            recent_messages=args.recent,
            summary_batch_size=args.batch,
        )


def ask_and_print(
    agent: ChatAgent,
    message: str,
    provider: str | None,
    thinking: str | None,
    **compression_options,
) -> int:
    try:
        reply = agent.ask(
            message,
            provider_id=provider,
            thinking_level=thinking,
            **compression_options,
        )
    except AgentCancelledError as exc:
        print(f"Отменено: {exc}", file=sys.stderr)
        return 130
    except AgentContextLimitError as exc:
        print(f"Лимит контекста: {exc}", file=sys.stderr)
        print(_format_metrics(exc.token_metrics))
        return 2
    except (ValueError, AgentUnavailableError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"Агент> {reply.text}")
    current_usage = _format_usage(reply.usage)
    session_usage = _format_usage(reply.session_usage)
    print(
        f"       [{reply.provider} · {reply.model} · попыток: {len(reply.attempts)} · "
        f"reasoning: {thinking or agent.config.thinking_level} · токены: {current_usage} · "
        f"сессия: {session_usage}]"
    )
    print(_format_metrics(reply.token_metrics))
    compression = reply.compression
    print(
        "       Сжатие: "
        f"{compression.get('status', '—')} · summary r{compression.get('summary_revision', 0)} · "
        f"сжато сообщений {compression.get('summarized_message_count', 0)} · "
        f"дословно {compression.get('verbatim_message_count', 0)} · "
        f"экономия ≈{compression.get('estimated_tokens_saved_this_request', 0)} токенов"
    )
    return 0


def _format_usage(usage: TokenUsage) -> str:
    if not usage.reported:
        suffix = "" if usage.complete else f", неизвестных вызовов {usage.unknown_calls}"
        return f"н/д{suffix}"
    completeness = "полная" if usage.complete else f"неполная, неизвестных вызовов {usage.unknown_calls}"
    return (
        f"вход {usage.input_tokens}, выход {usage.output_tokens}, "
        f"всего {usage.total_tokens}, reasoning {usage.reasoning_tokens}, {completeness}"
    )


def _fmt_count(metrics: dict, key: str) -> str:
    item = metrics.get(key) or {}
    if not isinstance(item, dict):
        return "н/д"
    prefix = "≈" if item.get("is_estimate") else ""
    value = item.get("value")
    return f"{prefix}{value}" if value is not None else "н/д"


def _format_metrics(metrics: dict) -> str:
    budget = metrics.get("context_budget") or {}
    visible = _fmt_count(metrics, "visible_answer_tokens")
    history_after = _fmt_count(metrics, "history_tokens_after")
    return (
        "       Метрики: "
        f"новое сообщение {_fmt_count(metrics, 'current_message_tokens')} · "
        f"история до {_fmt_count(metrics, 'history_tokens_before')} · "
        f"вход API {_fmt_count(metrics, 'request_tokens_before_send')} · "
        f"видимый ответ {visible} · история после {history_after} · "
        f"контекст {budget.get('request_tokens', 'н/д')}/"
        f"{budget.get('context_window_tokens') or 'н/д'} "
        f"(резерв ответа {budget.get('response_reserve_tokens', 'н/д')})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
