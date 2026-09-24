"""Integration checks using the actual Day 19 stdio MCP process."""

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator
import pytest


DAY = Path(__file__).resolve().parents[1] / "day19-mcp-composition"
sys.path.insert(0, str(DAY))
from pipeline import run


@pytest.fixture(autouse=True)
def plain_mode(monkeypatch):
    monkeypatch.setenv("DAY19_SUMMARY_MODE", "plain")


def test_three_real_calls_pass_data_and_write_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DAY19_OUTPUT_DIR", str(tmp_path))
    result = asyncio.run(run("MCP"))
    assert result["server"] == "day19-composition"
    assert [tool["name"] for tool in result["catalog"]] == ["search", "summarize", "saveToFile"]
    for tool in result["catalog"]:
        Draft202012Validator.check_schema(tool["inputSchema"])
    search, summarize, save = result["trace"]
    assert [step["tool"] for step in result["trace"]] == ["search", "summarize", "saveToFile"]
    assert summarize["arguments"]["items"] == search["result"]["items"]
    assert summarize["arguments"]["run_id"] == search["result"]["run_id"]
    assert save["arguments"]["summary"] == summarize["result"]["summary"]
    assert save["arguments"]["source_ids"] == summarize["result"]["source_ids"]
    assert save["arguments"]["mode"] == "local"
    assert save["arguments"]["model"] is None
    assert Path(result["file"]).parent == tmp_path
    assert Path(result["file"]).read_text(encoding="utf-8") == result["content"]


def test_empty_search_still_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("DAY19_OUTPUT_DIR", str(tmp_path))
    result = asyncio.run(run("несуществующийзапрос"))
    assert result["trace"][0]["result"]["items"] == []
    assert result["trace"][1]["result"]["source_count"] == 0
    assert "ничего не найдено" in result["content"]


def test_write_error_stops_chain(tmp_path, monkeypatch):
    blocked = tmp_path / "occupied"
    blocked.write_text("file", encoding="utf-8")
    monkeypatch.setenv("DAY19_OUTPUT_DIR", str(blocked))
    with pytest.raises(Exception):
        asyncio.run(run("MCP"))
    assert blocked.read_text(encoding="utf-8") == "file"


def test_default_cli(tmp_path):
    import subprocess
    result = subprocess.run([sys.executable, str(DAY / "pipeline.py")], capture_output=True, text=True, encoding="utf-8", timeout=40, env={**os.environ, "DAY19_OUTPUT_DIR": str(tmp_path), "PYTHONUTF8": "1"})
    assert result.returncode == 0, result.stderr
    assert all(name in result.stdout for name in ("search:", "summarize:", "saveToFile:"))


def test_web_uses_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("DAY19_OUTPUT_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("day19_web", DAY / "web_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = module.create_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(url + "/api/run", json.dumps({"query": "MCP"}).encode(), {"Content-Type": "application/json", "Origin": url})
        with urlopen(request, timeout=40) as response:
            result = json.load(response)
        assert [step["tool"] for step in result["trace"]] == ["search", "summarize", "saveToFile"]
        assert Path(result["file"]).exists()
        invalid = Request(url + "/api/run", b'{"query":""}', {"Content-Type": "application/json", "Origin": url})
        with pytest.raises(HTTPError) as error:
            urlopen(invalid, timeout=5)
        assert error.value.code == 400
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
