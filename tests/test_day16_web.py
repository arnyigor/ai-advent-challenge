import importlib.util
import json
from pathlib import Path
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

DAY = Path(__file__).resolve().parents[1] / "day16-mcp-connection"


@pytest.fixture
def api():
    sys.path.insert(0, str(DAY))
    try:
        spec = importlib.util.spec_from_file_location("day16_web", DAY / "web_server.py")
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
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(base, body, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = Request(base + "/api/discover", data=json.dumps(body).encode(), headers=headers)
    return urlopen(request, timeout=75)


def test_profiles_do_not_expose_launch_commands(api):
    with urlopen(api + "/api/servers") as response:
        profiles = json.load(response)["servers"]
    assert {profile["id"] for profile in profiles} == {"jarvis", "demo"}
    assert all("command" not in profile for profile in profiles)
    with urlopen(api) as response:
        assert "Инструменты вашего MCP" in response.read().decode()


def test_web_real_discovery_and_trace(api):
    with post(api, {"server_id": "demo"}, origin=api) as response:
        result = json.load(response)
    assert result["handshake"] == "ok"
    assert {tool["name"] for tool in result["tools"]} == {"add", "greet"}
    assert [event["stage"] for event in result["events"]] == ["starting", "initialized", "listed", "closed"]
    assert result["sessionClosed"] is True


def test_unknown_profile_cannot_execute_command(api):
    with pytest.raises(HTTPError) as caught:
        post(api, {"server_id": "unknown", "command": ["arbitrary"]})
    assert caught.value.code == 400


def test_other_site_cannot_launch_mcp(api):
    with pytest.raises(HTTPError) as caught:
        post(api, {"server_id": "demo"}, origin="https://example.org")
    assert caught.value.code == 403
