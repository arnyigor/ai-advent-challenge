"""Run the same long dialogue with full and compressed context."""

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


FACT_TURNS = [
    "Запомни для финальной проверки: код проекта — Маяк-17. Ответь только: принято.",
    "Для проекта выбран город Казань. Это важный факт. Ответь только: принято.",
    "Утверждённый бюджет проекта — 480 000 рублей. Ответь только: принято.",
    "Финальный отчёт нужно отдать в формате PDF. Ответь только: принято.",
]

FILLER_TURNS = [
    "Обсудим нейтральный фон: перечисли три преимущества коротких ежедневных заметок.",
    "Назови одним предложением пользу нумерованных списков в рабочем журнале.",
    "Сформулируй короткое напоминание регулярно проверять резервные копии.",
    "Одной строкой объясни, зачем фиксировать дату решения в протоколе.",
]

PROBES = [
    ("Какой код проекта? Ответь только кодом.", ("маяк17",)),
    ("Какой город выбран для проекта? Ответь одним словом.", ("казань",)),
    ("Какой бюджет утверждён? Ответь только числом.", ("480000",)),
    ("В каком формате нужен финальный отчёт? Ответь одним словом.", ("pdf",)),
]

BACKGROUND_WORDS = (
    "журнал маршрут секция архив заметка календарь команда задача отчёт "
    "проверка статус решение версия документ таблица встреча план риск этап"
).split()


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]", "", text.lower())


def setup_messages(background_words: int = 180) -> list[str]:
    """Add deterministic neutral context so summary cost can amortize."""
    result = []
    bases = [*FACT_TURNS, *FILLER_TURNS]
    for index, base in enumerate(bases):
        background = " ".join(
            BACKGROUND_WORDS[(index + offset) % len(BACKGROUND_WORDS)]
            for offset in range(background_words)
        )
        result.append(f"{base}\nНейтральный блок {index + 1}: {background}.")
    return result


def build_agent(session_id: str, *, compression_enabled: bool, provider_id: str) -> ChatAgent:
    providers = [provider for provider in create_default_providers() if provider.id == provider_id]
    if not providers:
        raise ValueError(f"Неизвестный провайдер: {provider_id}")
    if not providers[0].available():
        raise RuntimeError(f"Провайдер {provider_id} не настроен")
    store = SQLiteHistoryStore(DAY_DIR / "comparison.db")
    config = AgentConfig(
        compression_enabled=compression_enabled,
        recent_messages=6,
        summary_batch_size=10,
        summary_max_output_tokens=384,
        temperature=0,
        max_output_tokens=128,
    )
    agent = ChatAgent(providers, config=config, history_store=store, session_id=session_id)
    agent.reset()
    return agent


def run_mode(name: str, *, compression_enabled: bool, provider_id: str) -> dict:
    agent = build_agent(
        f"day09-{name}", compression_enabled=compression_enabled, provider_id=provider_id
    )
    turns = []
    setup = setup_messages()
    for index, message in enumerate(setup, start=1):
        reply = agent.ask(message, provider_id=provider_id)
        turns.append(
            {
                "kind": "setup",
                "index": index,
                "usage": reply.usage.__dict__,
                "request_tokens_estimate": reply.token_metrics["request_tokens_before_send"]["value"],
            }
        )

    correct = 0
    probe_results = []
    for index, (question, accepted) in enumerate(PROBES, start=1):
        reply = agent.ask(question, provider_id=provider_id)
        answer = reply.text
        normalized = normalize(answer)
        passed = any(value in normalized for value in accepted)
        correct += int(passed)
        probe_results.append(
            {
                "index": index,
                "question": question,
                "answer": answer,
                "passed": passed,
                "usage": reply.usage.__dict__,
                "compression": reply.compression,
            }
        )

    usage = agent.session_usage
    logs = agent.request_log()
    return {
        "compression_enabled": compression_enabled,
        "quality_score": round(correct / len(PROBES) * 100, 1),
        "correct_probes": correct,
        "total_probes": len(PROBES),
        "total_input_tokens": usage.input_tokens,
        "total_output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "usage_reported": usage.reported,
        "api_calls": usage.known_calls + usage.unknown_calls,
        "summary_calls": sum(1 for row in logs if row["status"] == "summary_ok"),
        "final_summary": agent.summary.to_dict(),
        "setup_turns": turns,
        "probes": probe_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 9 full-history vs summary comparison")
    parser.add_argument("--provider", default="deepseek")
    args = parser.parse_args()

    full = run_mode("full", compression_enabled=False, provider_id=args.provider)
    compressed = run_mode("compressed", compression_enabled=True, provider_id=args.provider)
    baseline = full["total_input_tokens"]
    saving = (
        round((baseline - compressed["total_input_tokens"]) / baseline * 100, 1)
        if baseline
        else None
    )
    total_baseline = full["total_tokens"]
    total_saving = (
        round((total_baseline - compressed["total_tokens"]) / total_baseline * 100, 1)
        if total_baseline
        else None
    )
    result = {
        "schema": "day09-comparison-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "dialogue": {
            "setup_turns": len(FACT_TURNS) + len(FILLER_TURNS),
            "probe_turns": len(PROBES),
            "same_messages_for_both_modes": True,
            "background_words_per_setup_turn": 180,
            "recent_messages": 6,
            "summary_batch_size": 10,
        },
        "modes": {"full_history": full, "compressed": compressed},
        "comparison": {
            "input_tokens_saved": baseline - compressed["total_input_tokens"],
            "input_token_saving_percent": saving,
            "total_tokens_saved": total_baseline - compressed["total_tokens"],
            "total_token_saving_percent": total_saving,
            "summary_output_overhead_tokens": (
                compressed["total_output_tokens"] - full["total_output_tokens"]
            ),
            "quality_delta_points": compressed["quality_score"] - full["quality_score"],
        },
    }
    output = DAY_DIR / "results" / "comparison.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["comparison"], ensure_ascii=False, indent=2))
    print(f"Written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
