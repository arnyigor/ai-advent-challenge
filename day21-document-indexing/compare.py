"""Evaluate retrieval quality and physical characteristics of both indexes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

from embeddings import Embedder, create_embedder
from index_store import index_stats, search
from day21_pipeline import DEFAULT_INDEX_DIR, DEFAULT_MODEL

DAY = Path(__file__).resolve().parent
DEFAULT_QUERIES = DAY / "benchmark_queries.json"
DEFAULT_REPORT = DAY / "results" / "comparison.json"


def compare_indexes(
    *,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    queries_path: Path | str = DEFAULT_QUERIES,
    output_path: Path | str | None = DEFAULT_REPORT,
    model_name: str = DEFAULT_MODEL,
    device: str = "cpu",
    embedder: Embedder | None = None,
) -> dict:
    target = Path(index_dir).resolve()
    queries = json.loads(Path(queries_path).read_text(encoding="utf-8"))
    active_embedder = embedder or create_embedder(model_name, device=device)
    report = {"embedding_model": active_embedder.name, "queries": len(queries), "strategies": {}, "cases": []}
    per_strategy = {name: {"ranks": [], "scores": []} for name in ("fixed", "structure")}
    for case in queries:
        vector = active_embedder.encode_query(case["query"])
        case_result = {**case, "results": {}}
        relevant_sources = set(case.get("relevant_sources", [case.get("source")]))
        for name in ("fixed", "structure"):
            found = search(target / f"{name}.sqlite3", vector, top_k=5)
            rank = next((index for index, item in enumerate(found, 1) if item["source"] in relevant_sources), None)
            score = next((item["score"] for item in found if item["source"] in relevant_sources), None)
            per_strategy[name]["ranks"].append(rank)
            if score is not None:
                per_strategy[name]["scores"].append(score)
            case_result["results"][name] = {"rank": rank, "score": score, "top": found[:3]}
        report["cases"].append(case_result)
    for name in ("fixed", "structure"):
        ranks = per_strategy[name]["ranks"]
        scores = per_strategy[name]["scores"]
        physical = index_stats(target / f"{name}.sqlite3")
        physical["index_file"] = Path(physical.pop("path")).name
        report["strategies"][name] = {
            **physical,
            "hit_at_1": round(sum(rank == 1 for rank in ranks) / len(ranks), 3),
            "hit_at_5": round(sum(rank is not None and rank <= 5 for rank in ranks) / len(ranks), 3),
            "mrr_at_5": round(sum(1 / rank if rank else 0 for rank in ranks) / len(ranks), 3),
            "avg_relevant_score": round(statistics.mean(scores), 4) if scores else None,
        }
    if output_path:
        output = Path(output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    print(json.dumps(compare_indexes(index_dir=args.index_dir, model_name=args.model, device=args.device, output_path=args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
