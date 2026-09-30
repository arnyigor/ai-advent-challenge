"""Evaluate baseline RAG versus rewritten and similarity-filtered RAG."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from rag_agent import (
    DEFAULT_MODEL,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TOP_K_AFTER,
    DEFAULT_TOP_K_BEFORE,
    RagAgent,
)

DAY = Path(__file__).resolve().parent
ROOT = DAY.parent
DEFAULT_QUESTIONS = ROOT / "day22-first-rag-request" / "control_questions.json"
DEFAULT_REPORT = DAY / "results" / "comparison.json"


def load_questions(path: Path | str = DEFAULT_QUESTIONS) -> list[dict]:
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(values, list) or len(values) != 10:
        raise ValueError("Контрольный набор должен содержать ровно 10 вопросов")
    return values


def score_answer(answer: str, required_terms: list[str]) -> dict:
    folded = answer.casefold()
    compact_answer = re.sub(r"[^a-zа-я0-9]", "", folded)
    hits = [
        term
        for term in required_terms
        if term.casefold() in folded
        or re.sub(r"[^a-zа-я0-9]", "", term.casefold()) in compact_answer
    ]
    return {
        "term_hits": hits,
        "term_total": len(required_terms),
        "answer_score": round(len(hits) / len(required_terms), 3) if required_terms else 1.0,
    }


def score_sources(sources: list[dict], expected_sources: list[str]) -> dict:
    retrieved = list(dict.fromkeys(item["source"] for item in sources))
    hits = [source for source in expected_sources if source in retrieved]
    return {
        "retrieved_sources": retrieved,
        "source_hits": hits,
        "source_total": len(expected_sources),
        "source_recall": round(len(hits) / len(expected_sources), 3) if expected_sources else 1.0,
    }


def _average(rows: list[dict], mode: str, field: str) -> float:
    return round(sum(float(row[mode][field]) for row in rows) / len(rows), 3)


def evaluate(agent: RagAgent, questions: list[dict]) -> dict:
    rows = []
    for item in questions:
        compared = agent.compare(item["question"])
        baseline = {
            **compared["baseline"],
            **score_answer(compared["baseline"]["answer"], item["required_terms"]),
            **score_sources(compared["baseline"]["sources"], item["expected_sources"]),
        }
        improved = {
            **compared["improved"],
            **score_answer(compared["improved"]["answer"], item["required_terms"]),
            **score_sources(compared["improved"]["sources"], item["expected_sources"]),
        }
        improved["kept_count"] = len(improved["sources"])
        improved["rejected_count"] = sum(not candidate["accepted"] for candidate in improved["candidates"])
        rows.append({**item, "baseline": baseline, "improved": improved})
    count = len(rows)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": agent.model,
        "embedding_model": agent.embedding_model,
        "questions": count,
        "settings": {
            "top_k_before": agent.top_k_before,
            "top_k_after": agent.top_k_after,
            "similarity_threshold": agent.similarity_threshold,
        },
        "summary": {
            "baseline_answer_score": _average(rows, "baseline", "answer_score"),
            "improved_answer_score": _average(rows, "improved", "answer_score"),
            "baseline_source_recall": _average(rows, "baseline", "source_recall"),
            "improved_source_recall": _average(rows, "improved", "source_recall"),
            "baseline_avg_prompt_chars": _average(rows, "baseline", "prompt_chars"),
            "improved_avg_prompt_chars": _average(rows, "improved", "prompt_chars"),
            "improved_avg_kept": _average(rows, "improved", "kept_count"),
            "improved_avg_rejected": _average(rows, "improved", "rejected_count"),
            "improved_wins": sum(row["improved"]["answer_score"] > row["baseline"]["answer_score"] for row in rows),
            "ties": sum(row["improved"]["answer_score"] == row["baseline"]["answer_score"] for row in rows),
            "baseline_wins": sum(row["improved"]["answer_score"] < row["baseline"]["answer_score"] for row in rows),
        },
        "items": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", default=str(DEFAULT_REPORT))
    parser.add_argument("--top-k-before", type=int, default=DEFAULT_TOP_K_BEFORE)
    parser.add_argument("--top-k-after", type=int, default=DEFAULT_TOP_K_AFTER)
    parser.add_argument("--threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    args = parser.parse_args()
    agent = RagAgent(
        model=args.model,
        top_k_before=args.top_k_before,
        top_k_after=args.top_k_after,
        similarity_threshold=args.threshold,
    )
    report = evaluate(agent, load_questions())
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(target), **report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
