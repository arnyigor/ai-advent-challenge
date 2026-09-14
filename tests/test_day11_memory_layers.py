import importlib
import json
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest


DAY_DIR = Path(__file__).resolve().parents[1] / "day11-memory-layers"


@pytest.fixture
def modules():
    names = ("agent", "memory_store", "providers", "web_server")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(DAY_DIR))
    try:
        yield importlib.import_module("agent"), importlib.import_module("memory_store")
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path.remove(str(DAY_DIR))


class FakeProvider:
    def __init__(self, reply_type):
        self.calls = []
        self.reply_type = reply_type

    def generate(self, *, system, messages):
        self.calls.append((system, messages))
        text = "Кедр-71, 15 декабря." if "Кедр-71" in system and "15 декабря" in system else "Сведений нет."
        return self.reply_type(text, "fake", "fake")


def test_layers_are_separate_and_scope_correctly(modules, tmp_path):
    _, store_mod = modules
    store = store_mod.MemoryStore(tmp_path)
    ids = dict(user_id="u1", session_id="s1", task_id="t1")
    store.save_fact("short", **ids, key="код", value="Кедр-71")
    store.save_fact("working", **ids, key="срок", value="15 декабря")
    store.save_fact("long", **ids, key="стиль", value="кратко")
    assert {p.name for p in tmp_path.glob("*.db")} == {"short.db", "working.db", "long.db"}
    assert store.snapshot(**ids) == {
        "short": {"facts": {"код": "Кедр-71"}, "messages": []},
        "working": {"срок": "15 декабря"},
        "long": {"стиль": "кратко"},
    }
    assert store.snapshot(user_id="u1", session_id="s2", task_id="t1")["short"]["facts"] == {}
    assert store.snapshot(user_id="u1", session_id="s2", task_id="t2")["working"] == {}
    assert store.snapshot(user_id="u1", session_id="s2", task_id="t2")["long"] == {"стиль": "кратко"}
    assert store.snapshot(user_id="u2", session_id="s1", task_id="t1")["long"] == {}


def test_explicit_selection_changes_sent_context_and_answer(modules, tmp_path):
    agent_mod, store_mod = modules
    store = store_mod.MemoryStore(tmp_path)
    ids = dict(user_id="u1", session_id="s1", task_id="t1")
    store.save_fact("short", **ids, key="код", value="Кедр-71")
    store.save_fact("working", **ids, key="срок", value="15 декабря")
    store.save_fact("long", **ids, key="стиль", value="кратко")
    provider = FakeProvider(agent_mod.ProviderReply)
    agent = agent_mod.MemoryAgent(store, provider)
    none = agent.ask(**ids, user_text="Назови код и срок", include=())
    assert none["answer"] == "Сведений нет."
    assert "Кедр-71" not in provider.calls[0][0]
    # A fresh session avoids leaking the baseline turn into the second prompt.
    store.save_fact("short", user_id="u1", session_id="s2", task_id="t1", key="код", value="Кедр-71")
    full = agent.ask(user_id="u1", session_id="s2", task_id="t1", user_text="Назови код и срок")
    assert full["answer"] == "Кедр-71, 15 декабря."
    assert "стиль: кратко" in provider.calls[1][0]
    assert len(store.messages(user_id="u1", session_id="s1")) == 2
    assert len(store.messages(user_id="u1", session_id="s2")) == 2


def test_failed_answer_does_not_enter_short_term(modules, tmp_path):
    agent_mod, store_mod = modules
    store = store_mod.MemoryStore(tmp_path)
    class BrokenProvider:
        def generate(self, **_kwargs):
            raise RuntimeError("offline")
    agent = agent_mod.MemoryAgent(store, BrokenProvider())
    ids = dict(user_id="u", session_id="s", task_id="t")
    with pytest.raises(RuntimeError):
        agent.ask(**ids, user_text="Привет")
    assert store.messages(user_id="u", session_id="s") == []


def test_web_routes_show_exact_memory_selection(modules, tmp_path):
    agent_mod, _ = modules
    web = importlib.import_module("web_server")
    server = web.create_server("127.0.0.1", 0, directory=tmp_path, provider=FakeProvider(agent_mod.ProviderReply))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    ids = {"user_id": "u", "session_id": "s", "task_id": "t"}

    def post(route, payload):
        request = Request(base + route, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    try:
        saved = post("/api/memory", {**ids, "layer": "working", "key": "срок", "value": "15 декабря"})
        assert saved["memory"]["working"] == {"срок": "15 декабря"}
        assert saved["memory"]["short"]["facts"] == {}
        assert saved["memory"]["long"] == {}
        preview = post("/api/preview", {**ids, "text": "Какой срок?", "include": ["working"]})
        assert preview["context"]["memory_used"]["working"] == {"срок": "15 декабря"}
        assert preview["context"]["memory_used"]["short"]["messages"] == []
        assert "срок: 15 декабря" in preview["context"]["system"]
        reply = post("/api/chat", {**ids, "text": "Какой срок?", "include": ["working"], "provider_id": "wormsoft"})
        assert reply["provider"] == "fake"
        assert reply["context"]["memory_used"]["working"] == {"срок": "15 декабря"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_wormsoft_adapter_uses_same_memory_context(modules, monkeypatch):
    _agent_mod, _store_mod = modules
    providers = importlib.import_module("providers")
    monkeypatch.setenv("WORMSOFT_API_KEY", "test-key")
    monkeypatch.setenv("WORMSOFT_BASE_URL", "https://example.test/api")
    sent = {}

    class Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "Кедр-71, 15 декабря."}}]}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(providers.requests, "post", fake_post)
    reply = providers.LiveProvider("wormsoft").generate(
        system="[РАБОЧАЯ ПАМЯТЬ]\n- срок: 15 декабря",
        messages=[{"role": "user", "content": "Какой срок?"}],
    )
    assert reply.model == "openai/gpt-oss:20b"
    assert sent["url"] == "https://example.test/api/chat/completions"
    assert sent["json"]["model"] == reply.model
    assert sent["json"]["messages"] == [
        {"role": "system", "content": "[РАБОЧАЯ ПАМЯТЬ]\n- срок: 15 декабря"},
        {"role": "user", "content": "Какой срок?"},
    ]


def test_evaluation_accepts_typographic_dash_and_space(modules):
    _agent_mod, _store_mod = modules
    evaluation = importlib.import_module("run_evaluation")
    assert evaluation.normalized("Кедр‑71, 15 декабря") == "кедр-71, 15 декабря"
