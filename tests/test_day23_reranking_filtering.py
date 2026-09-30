"""Day 23: query rewriting, similarity filtering, evaluation and web API."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DAY21 = ROOT / "day21-document-indexing"
DAY23 = ROOT / "day23-reranking-filtering"
for path in (DAY23, DAY21):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Day folders use script-style top-level imports. Remove same-named Day 22 modules
# during collection so the Day 23 server resolves its own local implementation.
for module_name in ("rag_agent", "evaluate", "web_server"):
    sys.modules.pop(module_name, None)

from day21_pipeline import build_indexes
from embeddings import HashEmbedder
from evaluate import evaluate, load_questions, score_answer
from rag_agent import RagAgent, RetrievedChunk, normalize_rewrite

SERVER_SPEC = importlib.util.spec_from_file_location("day23_web_server", DAY23 / "web_server.py")
SERVER_MODULE = importlib.util.module_from_spec(SERVER_SPEC)
assert SERVER_SPEC.loader is not None
SERVER_SPEC.loader.exec_module(SERVER_MODULE)
create_server = SERVER_MODULE.create_server


class FakeLlm:
    model_spec = "fake:test"

    def __init__(self):
        self.calls = []

    def call(self, prompt, gcfg=None, system_instruction=None):
        self.calls.append({"prompt": prompt, "gcfg": gcfg, "system": system_instruction})
        if "преобразуешь вопрос" in (system_instruction or ""):
            return "Запрос: Atlas ORBIT-47 подтверждение оператора"
        return "ORBIT-47 — только после подтверждения оператора. Источники: [1]"


class BrokenRewriteLlm(FakeLlm):
    def call(self, prompt, gcfg=None, system_instruction=None):
        if "преобразуешь вопрос" in (system_instruction or ""):
            raise RuntimeError("rewrite unavailable")
        return super().call(prompt, gcfg, system_instruction)


def make_agent(tmp_path, *, threshold=-1.0, llm=None):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "atlas.md").write_text(
        "# Atlas\n\nАварийный код ORBIT-47 используют только после подтверждения оператора.",
        encoding="utf-8",
    )
    (corpus / "other.md").write_text(
        "# Другое\n\nКаталог команд обновляется после handshake.",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"repo_root": ".", "sources": [{"root": "corpus", "include": ["*.md"]}]}),
        encoding="utf-8",
    )
    embedder = HashEmbedder(64)
    build_indexes(
        strategy="structure",
        manifest_path=manifest,
        index_dir=tmp_path / "indexes",
        model_name=embedder.name,
        embedder=embedder,
    )
    model = llm or FakeLlm()
    return (
        RagAgent(
            index_path=tmp_path / "indexes" / "structure.sqlite3",
            embedder=embedder,
            llm=model,
            top_k_before=2,
            top_k_after=1,
            similarity_threshold=threshold,
        ),
        model,
    )


def test_rewrite_is_single_line_and_has_safe_fallback():
    assert normalize_rewrite("  Запрос: tools/list   nextCursor\n ", "original") == ("tools/list nextCursor", False)
    assert normalize_rewrite("", "original") == ("original", True)
    assert normalize_rewrite("x" * 501, "original") == ("original", True)
    assert score_answer("Берём page.next_cursor", ["nextCursor"])["answer_score"] == 1.0


def test_compare_keeps_baseline_and_filters_rewritten_top_k(tmp_path):
    agent, llm = make_agent(tmp_path)
    result = agent.compare("Какой аварийный код Atlas?")
    assert result["baseline"]["search_query"] == result["question"]
    assert result["baseline"]["top_k_before"] == 1
    assert result["improved"]["search_query"] == "Atlas ORBIT-47 подтверждение оператора"
    assert result["improved"]["top_k_before"] == 2
    assert result["improved"]["top_k_after"] == 1
    assert len(result["improved"]["candidates"]) == 2
    assert len(result["improved"]["sources"]) == 1
    assert sum(item["accepted"] for item in result["improved"]["candidates"]) == 1
    assert "КОНТЕКСТ" in llm.calls[-1]["prompt"]


def test_threshold_rejects_candidates_and_skips_generation(tmp_path):
    agent, llm = make_agent(tmp_path, threshold=0.8)
    fixed = [
        RetrievedChunk(1, "a", "atlas.md", "Atlas", "Code", 0.79, "ORBIT-47"),
        RetrievedChunk(2, "b", "other.md", "Other", "Other", 0.2, "handshake"),
    ]
    agent.retrieve = lambda _query, *, top_k: fixed[:top_k]
    result = agent.ask_improved("Какой код?")
    assert result["sources"] == []
    assert all(not item["accepted"] for item in result["candidates"])
    assert result["prompt_chars"] == 0
    assert "не найдены" in result["answer"]
    assert len(llm.calls) == 1  # rewrite only


def test_heuristic_reranker_promotes_technical_evidence(tmp_path):
    agent, _ = make_agent(tmp_path, threshold=0.8)
    fixed = [
        RetrievedChunk(1, "generic", "overview.md", "Overview", "MCP", 0.86, "Каталог инструментов MCP."),
        RetrievedChunk(2, "code", "day16/mcp_client.py", "Client", "discover", 0.84, "page.next_cursor while tools list cursor"),
    ]
    agent.rewrite_query = lambda question: (question, False)
    agent.retrieve = lambda _query, *, top_k: fixed[:top_k]
    result = agent.ask_improved("Как tools/list использует nextCursor?")
    assert result["sources"][0]["chunk_id"] == "code"
    code_trace = next(item for item in result["candidates"] if item["chunk_id"] == "code")
    assert code_trace["original_rank"] == 2
    assert code_trace["reranked_rank"] == 1
    assert code_trace["accepted"] is True


def test_rewrite_failure_uses_original_question(tmp_path):
    agent, _ = make_agent(tmp_path, llm=BrokenRewriteLlm())
    result = agent.ask_improved("Какой код Atlas?")
    assert result["search_query"] == "Какой код Atlas?"
    assert result["rewrite_fallback"] is True


def test_evaluation_reports_both_modes_and_filter_counts(tmp_path):
    agent, _ = make_agent(tmp_path)
    question = {
        "id": "atlas",
        "question": "Какой аварийный код Atlas?",
        "expectation": "ORBIT-47",
        "required_terms": ["ORBIT-47"],
        "expected_sources": ["corpus/atlas.md"],
    }
    report = evaluate(agent, [question])
    assert report["summary"]["baseline_answer_score"] == 1.0
    assert report["summary"]["improved_answer_score"] == 1.0
    assert report["settings"] == {"top_k_before": 2, "top_k_after": 1, "similarity_threshold": -1.0}
    assert report["items"][0]["improved"]["rejected_count"] == 1
    assert len(load_questions()) == 10


def test_web_api_returns_baseline_improved_and_trace(tmp_path):
    agent, _ = make_agent(tmp_path)
    server = create_server(agent=agent)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"question": "Какой аварийный код Atlas?"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/compare",
            data=body,
            headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.server_port}"},
        )
        with urllib.request.urlopen(request) as response:
            value = json.load(response)
        assert value["baseline"]["mode"] == "baseline"
        assert value["improved"]["mode"] == "improved"
        assert value["improved"]["candidates"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
