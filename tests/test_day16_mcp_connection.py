"""Integration checks use actual SDK processes and stdio, not mocked discovery."""

import json
import os
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator

DAY = Path(__file__).resolve().parents[1] / "day16-mcp-connection"


def run_client(*args):
    return subprocess.run(
        [sys.executable, str(DAY / "mcp_client.py"), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def test_real_handshake_tools_and_reconnect():
    for _ in range(2):
        process = run_client("--json")
        assert process.returncode == 0, process.stderr
        result = json.loads(process.stdout)
        assert result["handshake"] == "ok"
        assert result["server"]["name"] == "day16-demo"
        assert result["protocolVersion"]
        assert result["transport"] == "stdio"
        assert result["sessionClosed"] is True
        tools = {tool["name"]: tool for tool in result["tools"]}
        assert len(result["tools"]) == 2
        assert set(tools) == {"add", "greet"}
        for tool in tools.values():
            assert tool["description"]
            Draft202012Validator.check_schema(tool["inputSchema"])
        schema = tools["add"]["inputSchema"]
        assert set(schema["required"]) == {"a", "b"}
        assert schema["properties"]["a"]["type"] == "integer"
        validator = Draft202012Validator(schema)
        assert validator.is_valid({"a": 1, "b": 2})
        assert not validator.is_valid({"a": "one", "b": 2})
        assert not validator.is_valid({"a": 1})
        assert tools["greet"]["inputSchema"]["required"] == ["name"]
        assert tools["greet"]["inputSchema"]["properties"]["name"]["type"] == "string"


def test_default_cli_prints_discovered_tools():
    process = run_client()
    assert process.returncode == 0, process.stderr
    assert "MCP handshake: OK" in process.stdout
    assert "Available tools: 2" in process.stdout
    assert "- add:" in process.stdout and "- greet:" in process.stdout
    assert "MCP session closed." in process.stdout


def test_external_command():
    process = run_client("--json", "--command", sys.executable, str(DAY / "demo_server.py"))
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["server"]["name"] == "day16-demo"
    assert {tool["name"] for tool in result["tools"]} == {"add", "greet"}


def test_missing_server_fails(tmp_path):
    process = run_client("--server", str(tmp_path / "missing.py"))
    assert process.returncode == 1
    assert "MCP connection failed:" in process.stderr
    assert not process.stdout


def test_server_exits_before_handshake(tmp_path):
    server = tmp_path / "exits.py"
    server.write_text("raise SystemExit(3)\n", encoding="utf-8")
    process = run_client("--server", str(server))
    assert process.returncode == 1
    assert "MCP connection failed:" in process.stderr
    assert not process.stdout


def test_unresponsive_server_times_out(tmp_path):
    server = tmp_path / "hangs.py"
    server.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    process = run_client("--server", str(server), "--timeout", "0.5")
    assert process.returncode == 1
    assert "TimeoutError" in process.stderr
    assert not process.stdout
