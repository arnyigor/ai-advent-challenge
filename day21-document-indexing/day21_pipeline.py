"""Build one or both local document indexes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from chunkers import chunk_documents
from embeddings import Embedder, create_embedder
from index_store import write_index
from loaders import DEFAULT_MANIFEST, load_corpus

DAY = Path(__file__).resolve().parent
DEFAULT_INDEX_DIR = DAY / "data" / "indexes"
DEFAULT_MODEL = os.environ.get("DAY21_EMBEDDING_MODEL", "intfloat/multilingual-e5-small")


def build_indexes(
    *,
    strategy: str = "all",
    manifest_path: Path | str = DEFAULT_MANIFEST,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    model_name: str = DEFAULT_MODEL,
    device: str = "cpu",
    chunk_size: int = 1200,
    embedder: Embedder | None = None,
) -> dict:
    if strategy not in {"fixed", "structure", "all"}:
        raise ValueError("strategy must be fixed, structure or all")
    documents, corpus = load_corpus(manifest_path)
    if not documents:
        raise RuntimeError("Corpus manifest did not resolve to any documents")
    active_embedder = embedder or create_embedder(model_name, device=device)
    target_dir = Path(index_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    strategies = ["fixed", "structure"] if strategy == "all" else [strategy]
    result = {"corpus": corpus, "embedding_model": active_embedder.name, "embedding_dim": active_embedder.dimension, "indexes": {}}
    for name in strategies:
        started = time.perf_counter()
        chunks = chunk_documents(documents, name, chunk_size=chunk_size)
        chunking_elapsed = time.perf_counter() - started
        started = time.perf_counter()
        vectors = active_embedder.encode_documents([item.text for item in chunks])
        embedding_elapsed = time.perf_counter() - started
        stats = write_index(
            target_dir / f"{name}.sqlite3", documents, chunks, vectors,
            embedding_model=active_embedder.name,
            embedding_dim=active_embedder.dimension,
            chunk_size=chunk_size,
        )
        stats.update({"chunking_elapsed_sec": round(chunking_elapsed, 3), "embedding_elapsed_sec": round(embedding_elapsed, 3)})
        result["indexes"][name] = stats
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=["fixed", "structure", "all"], default="all")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", default=os.environ.get("DAY21_EMBEDDING_DEVICE", "cpu"))
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    args = parser.parse_args()
    result = build_indexes(strategy=args.strategy, model_name=args.model, device=args.device, chunk_size=args.chunk_size, index_dir=args.index_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
