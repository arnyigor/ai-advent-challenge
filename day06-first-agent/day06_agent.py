"""CLI-интерфейс для первого агента."""

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
    AgentUnavailableError,
    ChatAgent,
    TokenUsage,
)
from providers import create_default_providers


def build_agent() -> ChatAgent:
    return ChatAgent(create_default_providers())


def main() -> int:
    provider_ids = [provider.id for provider in create_default_providers()]
    parser = argparse.ArgumentParser(description="Day 6 — первый LLM-агент")
    parser.add_argument("message", nargs="*", help="один вопрос; без аргумента — чат")
    parser.add_argument(
        "--provider", choices=provider_ids, default=None,
        help="принудительно использовать один провайдер вместо fallback-цепочки",
    )
    parser.add_argument(
        "--thinking", choices=GEMINI_THINKING_LEVELS, default=None,
        help="уровень reasoning для этого запуска",
    )
    args = parser.parse_args()
    agent = build_agent()

    if args.message:
        return ask_and_print(
            agent, " ".join(args.message), args.provider, args.thinking
        )

    provider = args.provider
    thinking = args.thinking or agent.config.thinking_level
    print(
        "Day 6 · First Agent · /reset — очистить историю · /exit — выход\n"
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
        ask_and_print(agent, message, provider, thinking)


def ask_and_print(
    agent: ChatAgent, message: str, provider: str | None, thinking: str | None
) -> int:
    try:
        reply = agent.ask(message, provider_id=provider, thinking_level=thinking)
    except AgentCancelledError as exc:
        print(f"Отменено: {exc}", file=sys.stderr)
        return 130
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
    return 0


def _format_usage(usage: TokenUsage) -> str:
    if not usage.reported:
        return "н/д"
    return (
        f"вход {usage.input_tokens}, выход {usage.output_tokens}, "
        f"всего {usage.total_tokens}, reasoning {usage.reasoning_tokens}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
