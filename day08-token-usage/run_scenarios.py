"""Day 8 scenario runner: three reproducible real-API sessions (A/B/C).

Runs against a single fixed provider/model for all three scenarios (plan
section 8 requirement) and writes a small, text-free JSON summary to
``results/scenarios.json``. Bulk content is generated algorithmically from a
seeded RNG so nothing bulky is stored in git; only the generator parameters
are recorded in the results.

Provider choice: DeepSeek (deepseek-v4-flash), confirmed 1,000,000-token
context window. Two smaller-window candidates were tried first and both
failed in practice (see model_config.json "hf"/"wormsoft" entries: HF ran out
of monthly Inference Providers credits mid-run; Wormsoft's Qwen3.8-27B has a
huge native context and just timed out instead of rejecting cleanly).
DeepSeek processes hundreds of thousands of real tokens in ~15s, so a genuine
overflow of its 1M window is reachable by accumulating history across a few
large turns, within the shared 60s HTTP timeout.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DAY_DIR.parents[0]
for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent import AgentContextLimitError, ChatAgent, TokenUsage
from history_store import SQLiteHistoryStore
from providers import create_default_providers
from token_metrics import estimate_tokens

PROVIDER_ID = "deepseek"
DB_PATH = DAY_DIR / "scenarios.db"
RESULTS_DIR = DAY_DIR / "results"
FACT_MESSAGE = "Запомни: код проекта — Маяк-17. Ответь кратко."
RECALL_MESSAGE = "Какой код проекта я назвал? Ответь одной строкой."

_VOCAB = (
    "карта маршрут отчёт датчик канал журнал архив сектор модуль реестр "
    "буфер индекс пакет узел процесс история событие сигнал статус команда "
    "запрос ответ система сессия модель контекст данные параметр значение "
    "таблица очередь ключ ссылка адрес блок кадр слой уровень граница"
).split()


def generate_block(index: int, word_count: int) -> str:
    """Deterministic, distinct-per-turn filler text (seeded on ``index``).

    Real DeepSeek tokenization runs ~1.45x higher than the local estimator
    for this vocabulary (measured: 199,726 estimated vs 289,047 real tokens
    for a 150,000-word block) because BPE splits Cyrillic words into more
    subword pieces than the estimator's word-length heuristic assumes.
    """
    rng = random.Random(1000 + index)
    body = " ".join(rng.choice(_VOCAB) for _ in range(word_count))
    return f"Блок {index}. {body}. Подтверди получение одной короткой фразой."


def generate_symbol_wall(char_count: int) -> str:
    """A single-symbol wall: the local estimator counts each character as
    its own token (worst case for that heuristic), while a real BPE
    tokenizer would merge the repeats into far fewer tokens. This makes it
    reliable for tripping the *local* context check without ever reaching
    the real API — the local estimate alone already exceeds the window.
    """
    return "!" * char_count


def build_agent(session_id: str) -> ChatAgent:
    store = SQLiteHistoryStore(DB_PATH)
    providers = create_default_providers()
    agent = ChatAgent(providers, history_store=store, session_id=session_id)
    agent.reset()
    return agent


def usage_dict(usage: TokenUsage) -> dict:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "reported": usage.reported,
    }


def metrics_summary(metrics: dict) -> dict:
    def count(key: str) -> dict | None:
        item = metrics.get(key)
        return {"value": item["value"], "is_estimate": item["is_estimate"]} if item else None

    budget = metrics.get("context_budget") or {}
    return {
        "current_message_tokens": count("current_message_tokens"),
        "history_tokens_before": count("history_tokens_before"),
        "request_tokens_before_send": count("request_tokens_before_send"),
        "visible_answer_tokens": count("visible_answer_tokens"),
        "history_tokens_after": count("history_tokens_after"),
        "context_budget": {
            "request_tokens": budget.get("request_tokens"),
            "context_window_tokens": budget.get("context_window_tokens"),
            "response_reserve_tokens": budget.get("response_reserve_tokens"),
            "overflow_tokens": budget.get("overflow_tokens"),
            "status": budget.get("status"),
        },
    }


def run_turn(agent: ChatAgent, text: str, *, label: str, **overrides) -> dict:
    try:
        reply = agent.ask(text, provider_id=PROVIDER_ID, **overrides)
    except AgentContextLimitError as exc:
        status = exc.attempts[-1]["status"] if exc.attempts else "context_limit_error"
        return {
            "label": label,
            "status": status,
            "error": str(exc),
            "metrics": metrics_summary(exc.token_metrics),
        }
    return {
        "label": label,
        "status": reply.status,
        "provider": reply.provider,
        "model": reply.model,
        "turn_index": reply.turn_index,
        "usage": usage_dict(reply.usage),
        "session_usage": usage_dict(reply.session_usage),
        "metrics": metrics_summary(reply.token_metrics),
        "answer_preview": reply.text[:120],
    }


def scenario_short() -> dict:
    agent = build_agent("day08-short")
    turns = [
        run_turn(agent, FACT_MESSAGE, label="fact"),
        run_turn(agent, RECALL_MESSAGE, label="recall"),
    ]
    return {"scenario": "A_short", "turns": turns}


def scenario_long(exchange_count: int = 10, block_words: int = 400) -> dict:
    agent = build_agent("day08-long")
    turns = [run_turn(agent, FACT_MESSAGE, label="fact")]
    for i in range(1, exchange_count + 1):
        turns.append(run_turn(agent, generate_block(i, block_words), label=f"filler_{i}"))
    turns.append(run_turn(agent, RECALL_MESSAGE, label="recall_after_long_history"))
    return {
        "scenario": "B_long",
        "generator": {"exchange_count": exchange_count, "block_words": block_words},
        "turns": turns,
    }


def scenario_overflow(max_padding_turns: int = 6, padding_words: int = 140_000) -> dict:
    agent = build_agent("day08-overflow")
    turns = [
        run_turn(agent, FACT_MESSAGE, label="fact"),
        run_turn(agent, "Подтверди получение одной короткой фразой.", label="warmup"),
    ]

    # Stage 1: local-check demo. The local estimator counts one token per
    # repeated symbol, so this wall alone estimates near the full window —
    # AgentContextLimitError should fire with status "local_context_limit"
    # and no API call is made (see generate_symbol_wall's docstring).
    wall = generate_symbol_wall(999_999)
    local_check = run_turn(agent, wall, label="oversized_local_check")
    local_check["generator"] = {"kind": "symbol_wall", "char_count": 999_999}
    turns.append(local_check)

    # Stage 2: real overflow demo. Word-diverse content tokenizes far less
    # efficiently for the real DeepSeek tokenizer than for the local
    # estimator (~1.45x more real tokens), so accumulating a few large
    # padding turns via the normal path (no force_overflow_api) crosses the
    # real 1,000,000-token window before the local estimate does, producing
    # a genuine provider-side rejection.
    for i in range(1, max_padding_turns + 1):
        block = generate_block(i, padding_words)
        turn = run_turn(agent, block, label=f"padding_{i}")
        turn["generator"] = {"kind": "word_diverse", "word_count": padding_words}
        turns.append(turn)
        if turn["status"] in ("provider_context_limit", "local_context_limit"):
            break

    history_len_before_reset = len(agent.history)
    agent.reset()
    recovery = run_turn(agent, "Скажи одно короткое приветствие.", label="recovery_after_reset")
    turns.append(recovery)

    return {
        "scenario": "C_overflow",
        "history_messages_before_reset": history_len_before_reset,
        "turns": turns,
    }


def main() -> int:
    RESULTS_DIR.mkdir(exist_ok=True)
    results = {
        "schema": "day8-scenarios-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": PROVIDER_ID,
        "scenarios": [scenario_short(), scenario_long(), scenario_overflow()],
    }
    out_path = RESULTS_DIR / "scenarios.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
