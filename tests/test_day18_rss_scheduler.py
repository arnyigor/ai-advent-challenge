from pathlib import Path
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

DAY = Path(__file__).resolve().parents[1] / "day18-rss-scheduler"
sys.path.insert(0, str(DAY))
from feed_store import collect, recent_articles, status, reset_state, recent_runs
from digest import build_digest, latest_digest
from day18_providers import fallback, OPENROUTER_MODEL, GEMINI_MODELS


class Response:
    content = b"<rss><channel><item><title>AI news</title><link>https://habr.com/ru/articles/123/</link><pubDate>today</pubDate></item></channel></rss>"
    def raise_for_status(self):
        pass


def test_collect_deduplicates_and_persists(tmp_path):
    path = tmp_path / "feed.db"
    fetch = lambda *args, **kwargs: Response()
    assert collect(db_path=path, fetch=fetch)["inserted"] == 1
    assert collect(db_path=path, fetch=fetch)["inserted"] == 0
    assert len(recent_articles(path)) == 1
    assert status(path)["last_run"]["inserted"] == 0


def test_fallback_order(monkeypatch):
    assert GEMINI_MODELS == ("gemini-3.7-flash", "gemini-3.5-flash", "gemini-2.5-flash")
    assert OPENROUTER_MODEL == "qwen/qwen3.8-27b:free"
    for key in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "WORMSOFT_API_KEY"):
        monkeypatch.setenv(key, "fake")
    seen = []
    def call(provider, prompt):
        seen.append(provider)
        if provider != "wormsoft":
            raise ValueError("simulated limit")
        return "Итог " * 120, "qwen/qwen3.8:27b"
    result = fallback("news", call=call)
    assert seen == ["gemini-3.7-flash", "gemini-3.5-flash", "openrouter", "wormsoft"]
    assert result["provider"] == "wormsoft"
    assert [x["result"] for x in result["attempts"]] == ["failed", "failed", "failed", "ok"]


def test_plain_digest_when_all_models_fail(tmp_path, monkeypatch):
    for key in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "WORMSOFT_API_KEY"):
        monkeypatch.setenv(key, "fake")
    path = tmp_path / "feed.db"
    collect(db_path=path, fetch=lambda *args, **kwargs: Response())
    result = build_digest(db_path=path, call=lambda *_: (_ for _ in ()).throw(ValueError("offline")))
    assert result["provider"] == "plain"
    stored = latest_digest(db_path=path)["digest"]
    assert "https://habr.com/ru/articles/123/" in stored["body"]
    assert "Темы выпуска" in stored["body"]
    assert len(stored["attempts"]) == 5
    with pytest.raises(ValueError, match="No new articles"):
        build_digest(db_path=path, call=lambda *_: ("duplicate", "model"))


def test_plain_mode_skips_model_calls(tmp_path, monkeypatch):
    path = tmp_path / "feed.db"
    collect(db_path=path, fetch=lambda *args, **kwargs: Response())
    monkeypatch.setenv("DAY18_DIGEST_MODE", "plain")
    import digest
    monkeypatch.setattr(digest, "generate", lambda *_: pytest.fail("model called in plain mode"))
    result = build_digest(db_path=path)
    assert result["provider"] == "plain"
    assert result["attempts"] == []
    assert "AI news" in result["body"]


def test_reset_clears_demo_data(tmp_path, monkeypatch):
    path = tmp_path / "feed.db"
    collect(db_path=path, fetch=lambda *args, **kwargs: Response())
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    build_digest(db_path=path, call=lambda *_: ("Сводка " * 100, "model"))
    assert status(path)["articles"] == 1
    assert reset_state(path) == {"articles": 0, "runs": 0, "digests": 0}
    assert status(path) == {"articles": 0, "last_run": None}
    assert recent_runs(path) == []
    assert latest_digest(db_path=path)["digest"] is None


def test_periodic_scheduler_runs_both_jobs(tmp_path, monkeypatch):
    import scheduler
    stop = threading.Event()
    events = []
    monkeypatch.setattr(scheduler, "collect", lambda **_: {"inserted": 1})
    monkeypatch.setattr(scheduler, "build_digest", lambda **_: {"provider": "test"})
    def on_event(job, result):
        events.append((job, result))
        if job == "digest":
            stop.set()
    thread = threading.Thread(target=scheduler.run_schedule, kwargs={"collect_seconds": 1, "digest_seconds": 1, "db_path": tmp_path / "feed.db", "stop": stop, "on_event": on_event})
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert {job for job, _ in events} == {"collect", "digest"}
    assert len(scheduler.schedule_status(tmp_path / "feed.db")) == 2


@pytest.mark.asyncio
async def test_mcp_returns_persisted_digest(tmp_path, monkeypatch):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    import json
    path = tmp_path / "feed.db"
    collect(db_path=path, fetch=lambda *args, **kwargs: Response())
    build_digest(db_path=path, call=lambda *_: ("Сводка " * 100, "model"))
    env = {"DAY18_DB_PATH": str(path)}
    params = StdioServerParameters(command=sys.executable, args=[str(DAY / "rss_mcp_server.py")], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert any(item.name == "get_habr_digest" for item in tools.tools)
            result = await session.call_tool("get_habr_digest", arguments={})
            assert not result.is_error
            payload = json.loads(result.content[0].text)
            assert payload["digest"]["body"].startswith("Обзор модели\n" + ("Сводка " * 100).strip())
            assert payload["status"]["articles"] == 1


def test_public_dashboard_is_read_only(tmp_path, monkeypatch):
    from http.server import ThreadingHTTPServer
    import json
    import public_server

    path = tmp_path / "feed.db"
    collect(db_path=path, fetch=lambda *args, **kwargs: Response())
    monkeypatch.setenv("DAY18_DIGEST_MODE", "plain")
    build_digest(db_path=path)
    monkeypatch.setattr(public_server, "DB_PATH", path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), public_server.Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/state") as response:
            state = json.load(response)
        assert state["status"]["articles"] == 1
        assert state["digest"]["provider"] == "plain"
        with urlopen(base + "/digest.txt") as response:
            assert "AI news" in response.read().decode()
        for request, code in ((Request(base + "/api/reset", data=b"", method="POST"), 405), (base + "/feed.sqlite3", 404)):
            with pytest.raises(HTTPError) as error:
                urlopen(request)
            assert error.value.code == code
        assert status(path)["articles"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
