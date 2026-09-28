"""Inspectable SQLite storage and cosine retrieval for document chunks."""

from __future__ import annotations

import array
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import Any

from models import Chunk, Document

SCHEMA = """
CREATE TABLE index_runs (
    id INTEGER PRIMARY KEY,
    strategy TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    chunk_size INTEGER NOT NULL,
    corpus_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE documents (
    source TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    file TEXT NOT NULL,
    language TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    char_count INTEGER NOT NULL
);
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    file TEXT NOT NULL,
    section TEXT NOT NULL,
    strategy TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    char_count INTEGER NOT NULL,
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY(source) REFERENCES documents(source)
);
CREATE TABLE chunk_embeddings (
    chunk_id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
);
CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, source, text, tokenize='unicode61');
CREATE INDEX idx_chunks_source ON chunks(source);
CREATE INDEX idx_chunks_section ON chunks(section);
"""


def _pack(values: list[float]) -> bytes:
    return array.array("f", values).tobytes()


def _unpack(blob: bytes) -> list[float]:
    values = array.array("f")
    values.frombytes(blob)
    return values.tolist()


def _corpus_hash(documents: list[Document]) -> str:
    import hashlib
    value = "\n".join(f"{item.source}:{item.content_hash}" for item in documents)
    return hashlib.sha256(value.encode()).hexdigest()


def write_index(
    path: Path | str,
    documents: list[Document],
    chunks: list[Chunk],
    embeddings: list[list[float]],
    *,
    embedding_model: str,
    embedding_dim: int,
    chunk_size: int,
) -> dict[str, Any]:
    if len(chunks) != len(embeddings):
        raise ValueError("Every chunk must have exactly one embedding")
    if any(len(vector) != embedding_dim for vector in embeddings):
        raise ValueError("Embedding dimensions are inconsistent")
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    started = time.perf_counter()
    with closing(sqlite3.connect(temporary)) as connection:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO index_runs(strategy, embedding_model, embedding_dim, chunk_size, corpus_hash, created_at) VALUES(?,?,?,?,?,?)",
            (chunks[0].strategy if chunks else "unknown", embedding_model, embedding_dim, chunk_size, _corpus_hash(documents), time.time()),
        )
        connection.executemany(
            "INSERT INTO documents VALUES(?,?,?,?,?,?)",
            [(item.source, item.title, item.file, item.language, item.content_hash, len(item.text)) for item in documents],
        )
        connection.executemany(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    item.chunk_id, item.source, item.title, item.file, item.section, item.strategy,
                    item.chunk_index, item.start_char, item.end_char, len(item.text), item.text,
                    json.dumps(item.metadata(), ensure_ascii=False, sort_keys=True),
                )
                for item in chunks
            ],
        )
        connection.executemany(
            "INSERT INTO chunk_embeddings VALUES(?,?,?,?)",
            [(item.chunk_id, embedding_model, embedding_dim, _pack(vector)) for item, vector in zip(chunks, embeddings)],
        )
        connection.executemany(
            "INSERT INTO chunk_fts(chunk_id, source, text) VALUES(?,?,?)",
            [(item.chunk_id, item.source, item.text) for item in chunks],
        )
        connection.commit()
    temporary.replace(path)
    stats = index_stats(path)
    stats["write_elapsed_sec"] = round(time.perf_counter() - started, 3)
    return stats


def _connect_readonly(path: Path | str) -> sqlite3.Connection:
    target = Path(path).resolve()
    if not target.is_file():
        raise FileNotFoundError(f"Index does not exist: {target}")
    connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def index_stats(path: Path | str) -> dict[str, Any]:
    target = Path(path).resolve()
    with closing(_connect_readonly(target)) as connection:
        run = dict(connection.execute("SELECT * FROM index_runs ORDER BY id DESC LIMIT 1").fetchone())
        lengths = [row[0] for row in connection.execute("SELECT char_count FROM chunks ORDER BY char_count")]
        documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        embeddings = connection.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    def percentile(fraction: float) -> int:
        return lengths[min(len(lengths) - 1, round((len(lengths) - 1) * fraction))] if lengths else 0
    return {
        **run,
        "documents": documents,
        "chunks": len(lengths),
        "embeddings": embeddings,
        "avg_chars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "median_chars": percentile(0.5),
        "p95_chars": percentile(0.95),
        "min_chars": min(lengths, default=0),
        "max_chars": max(lengths, default=0),
        "db_size_bytes": target.stat().st_size,
        "path": str(target),
    }


def search(path: Path | str, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
    with closing(_connect_readonly(path)) as connection:
        rows = connection.execute(
            """SELECT c.chunk_id, c.source, c.title, c.file, c.section, c.strategy,
                      c.chunk_index, c.start_char, c.end_char, c.char_count, c.text,
                      e.dim, e.embedding
               FROM chunks c JOIN chunk_embeddings e USING(chunk_id)"""
        ).fetchall()
    scored = []
    for row in rows:
        if row["dim"] != len(query_vector):
            raise ValueError("Query embedding dimension does not match the index")
        score = sum(left * right for left, right in zip(query_vector, _unpack(row["embedding"])))
        item = {key: row[key] for key in row.keys() if key not in {"embedding", "dim"}}
        item["score"] = round(float(score), 6)
        scored.append(item)
    scored.sort(key=lambda item: (-item["score"], item["chunk_id"]))
    return scored[:max(1, min(int(top_k), 50))]


def chunks_for_source(path: Path | str, source: str, limit: int = 20) -> list[dict[str, Any]]:
    with closing(_connect_readonly(path)) as connection:
        rows = connection.execute(
            "SELECT chunk_id, source, title, file, section, strategy, chunk_index, start_char, end_char, char_count, text FROM chunks WHERE source=? ORDER BY chunk_index LIMIT ?",
            (source, max(1, min(limit, 100))),
        ).fetchall()
    return [dict(row) for row in rows]


def list_sources(path: Path | str) -> list[dict[str, Any]]:
    with closing(_connect_readonly(path)) as connection:
        rows = connection.execute(
            "SELECT d.source, d.title, d.file, d.language, COUNT(c.chunk_id) AS chunks FROM documents d LEFT JOIN chunks c USING(source) GROUP BY d.source ORDER BY d.source"
        ).fetchall()
    return [dict(row) for row in rows]
