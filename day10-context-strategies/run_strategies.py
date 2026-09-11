"""Run one ТЗ-scenario through all three context strategies and compare.

Одинаковые 12 setup-сообщений и 5 контрольных вопросов для каждой стратегии,
один провайдер и одна модель. Ветвление дополнительно проверяется отдельным
сценарием: checkpoint, две ветки, независимое продолжение.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DAY_DIR.parent
for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent import AgentConfig, ChatAgent
from history_store import SQLiteHistoryStore
from providers import create_default_providers
from strategies import STRATEGIES, STRATEGY_LABELS


RECENT_MESSAGES = 6

# 12 ходов сбора ТЗ. Первые пять несут факты, которые к моменту проверки
# гарантированно выходят за окно последних шести сообщений.
SETUP_TURNS = [
    "Начинаем собирать ТЗ. Код проекта — Ирбис-4. Ответь только: принято.",
    "Целевая платформа — Android, минимальная версия 9. Ответь только: принято.",
    "Утверждённый бюджет — 640 000 рублей. Ответь только: принято.",
    "Крайний срок сдачи — 15 декабря. Ответь только: принято.",
    "Финальный отчёт сдаём в формате PDF. Ответь только: принято.",
    "Теперь нейтральная часть. Назови одним предложением пользу нумерованных требований.",
    "Одной строкой: зачем в ТЗ раздел «вне области работ»?",
    "Одной строкой: чем функциональные требования отличаются от нефункциональных.",
    "Сформулируй короткое напоминание фиксировать дату согласования.",
    "Одной строкой: зачем в ТЗ критерии приёмки.",
    "Одной строкой: чем полезен глоссарий терминов в ТЗ.",
    "Одной строкой: зачем указывать ответственного за каждый раздел.",
]

PROBES = [
    ("Какой код проекта? Ответь только кодом.", ("ирбис4",)),
    ("Какая целевая платформа? Ответь одним словом.", ("android",)),
    ("Какой бюджет утверждён? Ответь только числом.", ("640000",)),
    ("Какой крайний срок сдачи? Ответь только датой.", ("15декабря", "1512")),
    ("В каком формате сдаём финальный отчёт? Ответь одним словом.", ("pdf",)),
]

BRANCH_TURNS = {
    "mobile": "Ветка A: делаем только мобильное приложение. Перечисли три раздела ТЗ для неё.",
    "web": "Ветка B: делаем только веб-кабинет. Перечисли три раздела ТЗ для него.",
}
BRANCH_PROBE = "Что мы решили делать в этой ветке? Ответь одним словом: приложение или кабинет."


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]", "", text.lower())


def build_agent(session_id: str, *, strategy: str, provider_id: str) -> ChatAgent:
    providers = [p for p in create_default_providers() if p.id == provider_id]
    if not providers:
        raise ValueError(f"Неизвестный провайдер: {provider_id}")
    if not providers[0].available():
        raise RuntimeError(f"Провайдер {provider_id} не настроен")
    config = AgentConfig(
        strategy=strategy,
        recent_messages=RECENT_MESSAGES,
        facts_max_output_tokens=384,
        temperature=0,
        max_output_tokens=160,
    )
    store = SQLiteHistoryStore(DAY_DIR / "strategies.db")
    agent = ChatAgent(
        providers, config=config, history_store=store, session_id=session_id
    )
    agent.reset()
    return agent


def run_strategy(strategy: str, *, provider_id: str) -> dict:
    agent = build_agent(f"day10-{strategy}", strategy=strategy, provider_id=provider_id)
    setup = []
    for index, message in enumerate(SETUP_TURNS, start=1):
        reply = agent.ask(message, provider_id=provider_id)
        setup.append(
            {
                "index": index,
                "usage": reply.usage.__dict__,
                "request_tokens_estimate": reply.token_metrics[
                    "request_tokens_before_send"
                ]["value"],
                "verbatim_message_count": reply.context["verbatim_message_count"],
                "dropped_message_count": reply.context["dropped_message_count"],
                "facts_after_turn": reply.context["facts"],
            }
        )

    correct = 0
    probes = []
    for index, (question, accepted) in enumerate(PROBES, start=1):
        reply = agent.ask(question, provider_id=provider_id)
        passed = any(value in normalize(reply.text) for value in accepted)
        correct += int(passed)
        probes.append(
            {
                "index": index,
                "question": question,
                "answer": reply.text,
                "passed": passed,
                "usage": reply.usage.__dict__,
            }
        )

    usage = agent.session_usage
    logs = agent.request_log()
    return {
        "strategy": strategy,
        "label": STRATEGY_LABELS[strategy],
        "quality_score": round(correct / len(PROBES) * 100, 1),
        "correct_probes": correct,
        "total_probes": len(PROBES),
        "total_input_tokens": usage.input_tokens,
        "total_output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "usage_reported": usage.reported,
        "api_calls": usage.known_calls + usage.unknown_calls,
        "memory_calls": sum(1 for row in logs if row["status"] == "facts_ok"),
        "final_facts": agent.facts.to_dict(),
        "setup_turns": setup,
        "probes": probes,
    }


def run_branch_demo(*, provider_id: str) -> dict:
    """Checkpoint → две ветки → независимое продолжение и переключение."""
    agent = build_agent("day10-branchdemo", strategy="branching", provider_id=provider_id)
    for message in SETUP_TURNS[:3]:
        agent.ask(message, provider_id=provider_id)
    checkpoint = agent.checkpoint()

    branches = {}
    for branch_id, message in BRANCH_TURNS.items():
        agent.switch_branch("main")
        agent.create_branch(branch_id, fork_index=checkpoint, label=branch_id)
        agent.ask(message, provider_id=provider_id)
        branches[branch_id] = {"fork_index": checkpoint}

    # Переключаемся обратно: каждая ветка должна помнить только своё решение.
    for branch_id in BRANCH_TURNS:
        agent.switch_branch(branch_id)
        reply = agent.ask(BRANCH_PROBE, provider_id=provider_id)
        history = [message.content for message in agent.history]
        other = next(name for name in BRANCH_TURNS if name != branch_id)
        branches[branch_id].update(
            {
                "answer": reply.text,
                "message_count": len(history),
                "sees_own_decision": BRANCH_TURNS[branch_id] in history,
                "sees_other_branch": BRANCH_TURNS[other] in history,
                "shares_common_prefix": history[: checkpoint] ==
                [m.content for m in _main_history(agent)][: checkpoint],
            }
        )

    agent.switch_branch("main")
    usage = agent.session_usage
    return {
        "checkpoint_messages": checkpoint,
        "branches": branches,
        "isolated": all(
            item["sees_own_decision"] and not item["sees_other_branch"]
            for item in branches.values()
        ),
        "total_tokens": usage.total_tokens,
        "api_calls": usage.known_calls + usage.unknown_calls,
    }


def _main_history(agent: ChatAgent):
    current = agent.branch_id
    agent.switch_branch("main")
    history = agent.history
    agent.switch_branch(current)
    return history


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 10 strategy comparison")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument(
        "--only", choices=STRATEGIES, default=None, help="прогнать одну стратегию"
    )
    args = parser.parse_args()

    names = [args.only] if args.only else list(STRATEGIES)
    results = [run_strategy(name, provider_id=args.provider) for name in names]
    baseline = next(
        (item["total_input_tokens"] for item in results if item["strategy"] == "branching"),
        max(item["total_input_tokens"] for item in results),
    )
    for item in results:
        item["input_tokens_vs_full_branch_percent"] = (
            round((baseline - item["total_input_tokens"]) / baseline * 100, 1)
            if baseline
            else None
        )

    payload = {
        "schema": "day10-strategies-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "scenario": {
            "name": "Сбор ТЗ",
            "setup_turns": len(SETUP_TURNS),
            "probe_turns": len(PROBES),
            "same_messages_for_all_strategies": True,
            "recent_messages": RECENT_MESSAGES,
        },
        "strategies": results,
        "branching_demo": run_branch_demo(provider_id=args.provider)
        if args.only in (None, "branching")
        else None,
    }
    output = DAY_DIR / "results" / "strategies.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'Стратегия':<18}{'Качество':>10}{'Вход':>10}{'Выход':>9}{'Всего':>10}{'Вызовов':>9}")
    for item in results:
        print(
            f"{item['label']:<18}{item['correct_probes']}/{item['total_probes']:>8}"
            f"{item['total_input_tokens']:>10}{item['total_output_tokens']:>9}"
            f"{item['total_tokens']:>10}{item['api_calls']:>9}"
        )
    print(f"Written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
