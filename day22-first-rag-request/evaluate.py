"""Run the 10-question plain-vs-RAG quality comparison."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from rag_agent import DEFAULT_MODEL, RagAgent

DAY = Path(__file__).resolve().parent
DEFAULT_QUESTIONS = DAY / "control_questions.json"
DEFAULT_REPORT = DAY / "results" / "comparison.json"


def load_questions(path: Path | str = DEFAULT_QUESTIONS) -> list[dict]:
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(values, list) or len(values) != 10:
        raise ValueError("Контрольный набор должен содержать ровно 10 вопросов")
    return values


def score_answer(answer: str, required_terms: list[str]) -> dict:
    folded = answer.casefold()
    hits = [term for term in required_terms if term.casefold() in folded]
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


def evaluate(agent: RagAgent, questions: list[dict]) -> dict:
    rows = []
    for item in questions:
        compared = agent.compare(item["question"])
        plain_score = score_answer(compared["plain"]["answer"], item["required_terms"])
        rag_score = score_answer(compared["rag"]["answer"], item["required_terms"])
        retrieval = score_sources(compared["rag"]["sources"], item["expected_sources"])
        rows.append({**item, "plain": {**compared["plain"], **plain_score}, "rag": {**compared["rag"], **rag_score, **retrieval}})
    count = len(rows)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": agent.model,
        "embedding_model": agent.embedding_model,
        "questions": count,
        "summary": {
            "plain_answer_score": round(sum(row["plain"]["answer_score"] for row in rows) / count, 3),
            "rag_answer_score": round(sum(row["rag"]["answer_score"] for row in rows) / count, 3),
            "rag_source_recall": round(sum(row["rag"]["source_recall"] for row in rows) / count, 3),
            "rag_wins": sum(row["rag"]["answer_score"] > row["plain"]["answer_score"] for row in rows),
            "ties": sum(row["rag"]["answer_score"] == row["plain"]["answer_score"] for row in rows),
            "plain_wins": sum(row["rag"]["answer_score"] < row["plain"]["answer_score"] for row in rows),
        },
        "items": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", default=str(DEFAULT_REPORT))
    parser.add_argument("--top-k", type=int, default=4)
    args = parser.parse_args()
    report = evaluate(RagAgent(model=args.model, top_k=args.top_k), load_questions())
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(target), **report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

