"""CLI for Day 10: switch between sliding window, facts and branching."""

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
from history_store import BranchError, SQLiteHistoryStore
from providers import create_default_providers
from strategies import STRATEGIES, STRATEGY_LABELS


HELP = (
    "/strategy <" + "|".join(STRATEGIES) + "> · /facts · /branches · "
    "/checkpoint · /branch <имя> · /switch <имя> · /reset · /exit"
)


def build_agent(session_id: str = "cli") -> ChatAgent:
    store = SQLiteHistoryStore(DAY_DIR / "chat_history.db")
    return ChatAgent(create_default_providers(), history_store=store, session_id=session_id)


def main() -> int:
    provider_ids = [provider.id for provider in create_default_providers()]
    parser = argparse.ArgumentParser(description="Day 10 — стратегии управления контекстом")
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
        "--strategy", choices=STRATEGIES, default="sliding",
        help="стратегия управления контекстом",
    )
    parser.add_argument("--recent", type=int, default=6, help="последние N сообщений")
    parser.add_argument("--branch", default="main", help="активная ветка диалога")
    args = parser.parse_args()
    agent = build_agent(args.session)
    if args.branch != "main":
        agent.switch_branch(args.branch)

    strategy = args.strategy
    if args.message:
        return ask_and_print(
            agent,
            " ".join(args.message),
            args.provider,
            args.thinking,
            strategy=strategy,
            recent_messages=args.recent,
        )

    provider = args.provider
    thinking = args.thinking or agent.config.thinking_level
    print(
        f"Day 10 · Стратегии контекста · {HELP}\n"
        f"сессия: {args.session} · ветка: {agent.branch_id} · "
        f"восстановлено реплик: {len(agent.history) // 2} · "
        f"стратегия: {STRATEGY_LABELS[strategy]} · провайдер: {provider or 'авто'}"
    )
    while True:
        try:
            message = input(f"\n[{strategy}/{agent.branch_id}] Вы> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if message in {"/exit", "/quit"}:
            return 0
        if not message:
            continue
        if message.startswith("/"):
            strategy = handle_command(agent, message, strategy)
            continue
        ask_and_print(
            agent,
            message,
            provider,
            thinking,
            strategy=strategy,
            recent_messages=args.recent,
        )


def handle_command(agent: ChatAgent, message: str, strategy: str) -> str:
    """Возвращает (возможно изменённую) активную стратегию."""
    command, _, value = message.partition(" ")
    value = value.strip()
    try:
        if command == "/strategy":
            if value not in STRATEGIES:
                print(f"Агент> Допустимо: {', '.join(STRATEGIES)}")
                return strategy
            print(f"Агент> Стратегия: {STRATEGY_LABELS[value]}")
            return value
        if command == "/reset":
            agent.reset()
            print("Агент> История, факты, ветки и счётчики очищены.")
        elif command == "/facts":
            facts = agent.facts
            print(
                f"Агент> Факты (r{facts.revision}):\n{facts.render() or '  (пусто)'}"
            )
        elif command == "/checkpoint":
            print(f"Агент> Checkpoint здесь: сообщений в ветке {agent.checkpoint()}")
        elif command == "/branches":
            for row in agent.branches() or [{"branch_id": "main", "message_count": len(agent.history)}]:
                mark = "*" if row["branch_id"] == agent.branch_id else " "
                parent = row.get("parent_branch_id")
                origin = f" ← {parent}@{row.get('fork_index')}" if parent else ""
                print(f"Агент> {mark} {row['branch_id']} ({row.get('message_count', 0)} сообщений){origin}")
        elif command == "/branch":
            created = agent.create_branch(value)
            print(
                f"Агент> Ветка {created['branch_id']} создана от "
                f"{created['parent_branch_id']}@{created['fork_index']} и активна."
            )
        elif command == "/switch":
            print(f"Агент> Активная ветка: {agent.switch_branch(value)}")
        else:
            print(f"Агент> {HELP}")
    except (BranchError, ValueError, RuntimeError) as exc:
        print(f"Агент> Ошибка: {exc}")
    return strategy


def ask_and_print(
    agent: ChatAgent,
    message: str,
    provider: str | None,
    thinking: str | None,
    **context_options,
) -> int:
    try:
        reply = agent.ask(
            message, provider_id=provider, thinking_level=thinking, **context_options
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
    print(
        f"       [{reply.provider} · {reply.model} · попыток: {len(reply.attempts)} · "
        f"токены: {_format_usage(reply.usage)} · сессия: {_format_usage(reply.session_usage)}]"
    )
    print(_format_metrics(reply.token_metrics))
    context = reply.context
    window = context.get("recent_messages_limit")
    print(
        "       Контекст: "
        f"{context.get('strategy_label', '—')} · ветка {context.get('branch_id', 'main')} · "
        f"окно {window if window is not None else 'вся ветка'} · "
        f"дословно {context.get('verbatim_message_count', 0)} из "
        f"{context.get('raw_message_count', 0)} · "
        f"отброшено {context.get('dropped_message_count', 0)} · "
        f"фактов {context.get('facts_count', 0)} (r{context.get('facts_revision', 0)}) · "
        f"экономия ≈{context.get('estimated_tokens_saved_this_request', 0)} токенов"
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
    return (
        "       Метрики: "
        f"новое сообщение {_fmt_count(metrics, 'current_message_tokens')} · "
        f"история до {_fmt_count(metrics, 'history_tokens_before')} · "
        f"вход API {_fmt_count(metrics, 'request_tokens_before_send')} · "
        f"видимый ответ {_fmt_count(metrics, 'visible_answer_tokens')} · "
        f"контекст {budget.get('request_tokens', 'н/д')}/"
        f"{budget.get('context_window_tokens') or 'н/д'} "
        f"(резерв ответа {budget.get('response_reserve_tokens', 'н/д')})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
