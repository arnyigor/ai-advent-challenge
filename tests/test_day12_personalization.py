import importlib.util
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DAY = ROOT / "day12-personalization"
DAY11 = ROOT / "day11-memory-layers"


@pytest.fixture
def modules():
    names = ("agent", "memory_store", "providers", "personalized_agent", "profile_store", "web_server", "model_providers")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(DAY))
    sys.path.insert(1, str(DAY11))
    try:
        personal = importlib.import_module("personalized_agent")
        profiles = importlib.import_module("profile_store")
        spec = importlib.util.spec_from_file_location("day12_web_server", DAY / "web_server.py")
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        yield personal, profiles, server
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path.remove(str(DAY))
        sys.path.remove(str(DAY11))


def configured(tmp_path, modules):
    personal, profile_module, server = modules
    profiles = profile_module.ProfileStore(tmp_path)
    profiles.save("alice", {"address": "Анна", "style": "кратко", "format": "3 пункта", "constraints": "без англицизмов", "trigger": "напиши фичу", "roles": ["analyst", "developer", "reviewer"]})
    profiles.save("bob", {"address": "Борис", "style": "подробно", "format": "таблица", "constraints": "", "trigger": "", "roles": []})
    return personal.PersonalizedAgent(personal.MemoryStore(tmp_path), profiles, server.DemoProvider())


def kwargs(user, text="Привет"):
    return {"user_id": user, "session_id": "s", "task_id": "t", "user_text": text, "include": ()}


def test_profile_is_automatic_and_isolated(tmp_path, modules):
    agent = configured(tmp_path, modules)
    alice = agent.ask(**kwargs("alice"))
    bob = agent.ask(**kwargs("bob"))
    assert "Анна" in alice["answer"] and "Борис" in bob["answer"]
    assert "Формат: 3 пункта" in alice["context"]["system"]
    assert "Ограничения: без англицизмов" in alice["context"]["system"]
    assert "Анна" not in bob["context"]["system"]
    assert alice["context"]["included_layers"] == []


def test_ordered_workflow_and_normal_request(tmp_path, modules):
    agent = configured(tmp_path, modules)
    feature = agent.ask(**kwargs("alice", "НАПИШИ ФИЧУ заметок"))
    assert [step["role"] for step in feature["steps"]] == ["analyst", "developer", "reviewer"]
    assert feature["context"]["workflow"] == ["analyst", "developer", "reviewer"]
    assert agent.ask(**kwargs("alice", "Как дела?"))["steps"] == []
    assert agent.ask(**kwargs("bob", "Напиши фичу заметок"))["steps"] == []


def test_previous_role_output_and_day11_memory_are_passed(tmp_path, modules):
    class Spy:
        def __init__(self):
            self.calls = []

        def generate(self, *, system, messages):
            ProviderReply = modules[0].ProviderReply if hasattr(modules[0], "ProviderReply") else importlib.import_module("agent").ProviderReply
            self.calls.append((system, messages))
            return ProviderReply(f"шаг-{len(self.calls)}", "spy", "test")

    base = configured(tmp_path, modules)
    base.store.save_fact("working", user_id="alice", session_id="s", task_id="t", key="срок", value="15 декабря")
    spy = Spy()
    agent = modules[0].PersonalizedAgent(base.store, base.profiles, spy)
    agent.ask(user_id="alice", session_id="s", task_id="t", user_text="напиши фичу", include=("working",))
    assert len(spy.calls) == 3
    assert "15 декабря" in spy.calls[0][0]
    assert "analyst: шаг-1" in spy.calls[1][1][-1]["content"]
    assert "developer: шаг-2" in spy.calls[2][1][-1]["content"]


def test_failed_step_does_not_write_transcript(tmp_path, modules):
    class Broken:
        def generate(self, **_kwargs):
            raise RuntimeError("offline")
    base = configured(tmp_path, modules)
    agent = modules[0].PersonalizedAgent(base.store, base.profiles, Broken())
    try:
        agent.ask(**kwargs("alice", "напиши фичу"))
    except RuntimeError:
        pass
    else:
        assert False
    assert base.store.messages(user_id="alice", session_id="s") == []


def test_invalid_profile_is_rejected(tmp_path, modules):
    store = modules[1].ProfileStore(tmp_path)
    invalid = {"address": "A", "style": "", "format": "", "constraints": "", "trigger": "", "roles": ["developer"]}
    try:
        store.save("alice", invalid)
    except ValueError:
        pass
    else:
        assert False
