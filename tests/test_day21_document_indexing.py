"""Day 21: corpus, chunking, metadata, embeddings and SQLite retrieval."""

from __future__ import annotations

import json
from pathlib import Path
import sys

DAY = Path(__file__).resolve().parents[1] / "day21-document-indexing"
sys.path.insert(0, str(DAY))

from chunkers import chunk_documents, fixed_chunks, structural_chunks
from compare import compare_indexes
from embeddings import HashEmbedder
from index_store import chunks_for_source, index_stats, search
from loaders import load_corpus
from models import Document
from day21_pipeline import build_indexes


def document(text: str, language: str = "markdown") -> Document:
    return Document("docs/example.md", "Example", "example.md", language, text, "content-hash")


def test_manifest_has_required_corpus_volume():
    documents, stats = load_corpus()
    assert stats["files"] >= 30
    assert 20 <= stats["pages_at_500_words"] <= 35
    assert any(item.language == "python" for item in documents)
    assert any(item.language == "markdown" for item in documents)


def test_fixed_chunks_have_overlap_and_required_metadata():
    chunks = fixed_chunks(document("alpha " * 500), chunk_size=300, overlap=50)
    assert len(chunks) > 2
    assert chunks[1].start_char == chunks[0].end_char - 50
    assert chunks[0].strategy == "fixed"
    assert chunks[0].source and chunks[0].title and chunks[0].file
    assert chunks[0].section and chunks[0].chunk_id.startswith("fixed:")


def test_structural_markdown_respects_heading_boundaries():
    item = document("# Handbook\n\nIntro.\n\n## Install\n\nRun setup.\n\n## Verify\n\nRun tests.\n")
    chunks = structural_chunks(item, chunk_size=300)
    assert [chunk.section for chunk in chunks] == ["Handbook", "Handbook > Install", "Handbook > Verify"]
    assert "Run tests" not in chunks[1].text


def test_structural_python_uses_top_level_symbols():
    item = document('"""Module docs."""\n\nVALUE = 1\n\ndef run():\n    return VALUE\n\nclass Worker:\n    pass\n', "python")
    chunks = structural_chunks(item, chunk_size=300)
    assert [chunk.section for chunk in chunks] == ["module", "function run", "class Worker"]


def test_chunk_ids_are_stable_and_strategy_specific():
    item = document("# A\n\n" + "body " * 100)
    first = structural_chunks(item, 300)
    second = structural_chunks(item, 300)
    fixed = fixed_chunks(item, 300)
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert {chunk.chunk_id for chunk in first}.isdisjoint(chunk.chunk_id for chunk in fixed)


def test_build_search_and_compare_two_sqlite_indexes(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "alpha.md").write_text("# Alpha\n\nThe launch phrase is blue sunrise. " * 30, encoding="utf-8")
    (corpus / "beta.py").write_text('"""Beta tools."""\n\ndef answer():\n    return "orange moon"\n', encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"repo_root": ".", "sources": [{"root": "corpus", "include": ["*.md", "*.py"]}]}), encoding="utf-8")
    embedder = HashEmbedder(64)
    result = build_indexes(manifest_path=manifest, index_dir=tmp_path / "indexes", model_name=embedder.name, embedder=embedder, chunk_size=300)
    assert set(result["indexes"]) == {"fixed", "structure"}
    for name in ("fixed", "structure"):
        stats = index_stats(tmp_path / "indexes" / f"{name}.sqlite3")
        assert stats["documents"] == 2
        assert stats["chunks"] == stats["embeddings"] > 0
        found = search(tmp_path / "indexes" / f"{name}.sqlite3", embedder.encode_query("blue sunrise"))
        assert found[0]["source"] == "corpus/alpha.md"
        assert found[0]["section"]
    queries = tmp_path / "queries.json"
    queries.write_text(json.dumps([{"query": "blue sunrise", "relevant_sources": ["corpus/alpha.md"]}]), encoding="utf-8")
    report = compare_indexes(index_dir=tmp_path / "indexes", queries_path=queries, output_path=tmp_path / "comparison.json", model_name=embedder.name, embedder=embedder)
    assert report["strategies"]["fixed"]["hit_at_1"] == 1
    assert report["strategies"]["structure"]["hit_at_1"] == 1
    assert chunks_for_source(tmp_path / "indexes" / "structure.sqlite3", "corpus/alpha.md")[0]["chunk_id"].startswith("structure:")


def test_unknown_strategy_is_rejected():
    try:
        chunk_documents([document("text")], "semantic")
    except ValueError as exc:
        assert "Unknown" in str(exc)
    else:
        raise AssertionError("unknown strategy must fail")
