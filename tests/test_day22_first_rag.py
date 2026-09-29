"""Day 22: retrieval, prompt construction, scoring and web API."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DAY21 = ROOT / "day21-document-indexing"
DAY22 = ROOT / "day22-first-rag-request"
for path in (DAY22, DAY21):
    sys.path.insert(0, str(path))

from day21_pipeline import build_indexes
from embeddings import HashEmbedder
from evaluate import load_questions, score_answer, score_sources
from rag_agent import RagAgent, extract_answer, format_context

SERVER_SPEC = importlib.util.spec_from_file_location("day22_web_server", DAY22 / "web_server.py")
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
        return "ORBIT-47 — только после подтверждения оператора. Источники: [1]" if "КОНТЕКСТ" in prompt else "Код мне неизвестен."


def make_agent(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "atlas.md").write_text("# Atlas\n\nАварийный код ORBIT-47 используют только после подтверждения оператора.", encoding="utf-8")
    (corpus / "other.md").write_text("# Другое\n\nКаталог команд обновляется после handshake.", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"repo_root": ".", "sources": [{"root": "corpus", "include": ["*.md"]}]}), encoding="utf-8")
    embedder = HashEmbedder(64)
    build_indexes(strategy="structure", manifest_path=manifest, index_dir=tmp_path / "indexes", model_name=embedder.name, embedder=embedder)
    llm = FakeLlm()
    return RagAgent(index_path=tmp_path / "indexes" / "structure.sqlite3", embedder=embedder, llm=llm, top_k=2), llm


def test_control_set_has_ten_questions_with_expectations_and_sources():
    questions = load_questions()
    assert len(questions) == 10
    assert all(item["expectation"] and item["required_terms"] and item["expected_sources"] for item in questions)


def test_plain_and_rag_use_same_model_but_only_rag_retrieves(tmp_path):
    agent, llm = make_agent(tmp_path)
    compared = agent.compare("Какой аварийный код Atlas?")
    assert compared["plain"]["model"] == compared["rag"]["model"] == "fake:test"
    assert compared["plain"]["sources"] == []
    assert compared["rag"]["sources"][0]["source"] == "corpus/atlas.md"
    assert "КОНТЕКСТ" not in llm.calls[0]["prompt"]
    assert "КОНТЕКСТ" in llm.calls[1]["prompt"] and "[1] source=corpus/atlas.md" in llm.calls[1]["prompt"]
    assert format_context(agent.retrieve("ORBIT-47")).startswith("[1] source=")


def test_scores_terms_and_expected_sources():
    answer = score_answer("ORBIT-47 после подтверждения", ["ORBIT-47", "подтвержден", "SQLite"])
    sources = score_sources([{"source": "atlas.md"}, {"source": "other.md"}], ["atlas.md", "missing.md"])
    assert answer["answer_score"] == 0.667
    assert sources["source_recall"] == 0.5


def test_provider_response_extraction_skips_reasoning_parts():
    response = {"candidates": [{"content": {"parts": [{"text": "мысль", "thought": True}, {"text": "ответ"}]}}]}
    assert extract_answer(response) == "ответ"


def test_web_api_returns_side_by_side_comparison(tmp_path):
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
        assert value["plain"]["mode"] == "plain"
        assert value["rag"]["mode"] == "rag"
        assert value["rag"]["sources"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
