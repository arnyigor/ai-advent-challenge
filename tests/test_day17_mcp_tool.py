"""Real stdio MCP and HTTP integration checks for Day 17."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator
import pytest


DAY = Path(__file__).resolve().parents[1] / "day17-first-mcp-tool"


def run_agent(*arguments):
    return subprocess.run([sys.executable, str(DAY / "git_agent.py"), *arguments],
                          text=True, encoding="utf-8", capture_output=True, timeout=60,
                          env={**os.environ, "PYTHONUTF8": "1"})


@pytest.mark.parametrize("scope", ["summary", "latest_commit"])
def test_agent_calls_tool_and_uses_result(scope):
    process = run_agent(scope, "--json")
    assert process.returncode == 0, process.stderr
    data = json.loads(process.stdout)
    assert data["server"] == "day17-git"
    assert data["tool"] == "get_git_snapshot"
    assert data["arguments"] == {"scope": scope}
    assert data["result"]["scope"] == scope
    assert data["result"]["repository"] == "ai-advent-challenge"
    assert data["steps"] == ["initialize", "tools/list", "tools/call", "ответ агента"]
    Draft202012Validator.check_schema(data["inputSchema"])
    assert data["inputSchema"]["required"] == ["scope"]
    assert not Draft202012Validator(data["inputSchema"]).is_valid({"scope": "write"})
    if scope == "summary":
        assert data["result"]["branch"] in data["answer"]
        assert str(data["result"]["tracked_changes"]) in data["answer"] or data["result"]["clean_tracked_files"]
    else:
        assert data["result"]["short_hash"] in data["answer"]
        assert data["result"]["subject"] in data["answer"]


def test_default_cli_works():
    process = run_agent()
    assert process.returncode == 0, process.stderr
    assert "get_git_snapshot" in process.stdout
    assert "Агент:" in process.stdout


@pytest.fixture
def api():
    sys.path.insert(0, str(DAY))
    try:
        spec = importlib.util.spec_from_file_location("day17_web", DAY / "web_server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        server = module.create_server()
    finally:
        sys.path.remove(str(DAY))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def post(api, scope, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = Request(api + "/api/ask", json.dumps({"scope": scope}).encode(), headers)
    return urlopen(request, timeout=60)


def test_web_calls_real_tool(api):
    with urlopen(api) as response:
        assert "Агент вызывает MCP-инструмент" in response.read().decode()
    with post(api, "latest_commit", api) as response:
        data = json.load(response)
    assert data["tool"] == "get_git_snapshot"
    assert data["result"]["short_hash"] in data["answer"]


def test_web_rejects_invalid_request(api):
    with pytest.raises(HTTPError) as invalid:
        post(api, "write")
    assert invalid.value.code == 400
    with pytest.raises(HTTPError) as foreign:
        post(api, "summary", "https://example.org")
    assert foreign.value.code == 403
