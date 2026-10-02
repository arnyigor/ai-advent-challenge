"""Offline coverage: state invariants, store persistence, agent turn plumbing, web API."""
import importlib.util
import json
import sqlite3
from types import SimpleNamespace
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
DAY = ROOT / 'day25-rag-chat-memory'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ts = load('day25_task_state', DAY / 'task_state.py')
cs = load('day25_chat_store', DAY / 'chat_store.py')
ca = load('day25_chat_agent', DAY / 'chat_agent.py')

STATE = {'goal': 'Разобраться с дедупликацией RSS', 'clarified': ['интересует День 18'],
         'constraints': ['только стандартная библиотека'], 'terms': ['INSERT OR IGNORE']}


class FakeLLM:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []

    def call(self, prompt, *args, **kwargs):
        self.calls.append(prompt)
        try:
            value = next(self.values)
        except StopIteration:
            return ''
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


class FakeRag:
    def __init__(self, results):
        self.results = iter(results)
        self.queries = []
        self.model = 'fake'
        self.llm = FakeLLM([])

    def ask(self, query):
        self.queries.append(query)
        return next(self.results)


def rag_result(status='answered', answer='Дедупликация через INSERT OR IGNORE.', **overrides):
    base = {'status': status, 'answer': answer,
            'sources': [{'source': 'feed_store.py', 'section': 'collect', 'chunk_id': 'c1'}] if status == 'answered' else [],
            'quotes': [{'claim': 1, 'chunk_id': 'c1', 'source': 'feed_store.py', 'section': 'collect',
                        'quote': 'INSERT OR IGNORE INTO articles'}] if status == 'answered' else [],
            'claims': [{'text': answer, 'evidence': []}] if status == 'answered' else [],
            'reason': 'verified' if status == 'answered' else 'weak_context',
            'similarity_threshold': 0.83, 'candidates': [], 'retrieved_chunks': []}
    return {**base, **overrides}


def agent(tmp_path, llm_values, rag_results):
    return ca.ChatAgent(data_dir=tmp_path, llm=FakeLLM(llm_values), rag=FakeRag(rag_results), history_turns=3)


# ---------------------------------------------------------------- task state

def test_normalize_state_accepts_and_versions():
    state = ts.normalize_state('s1', STATE, None)
    assert state.version == 1 and state.goal.startswith('Разобраться')
    grown = ts.normalize_state('s1', {**STATE, 'terms': ['INSERT OR IGNORE', 'dedup']}, state)
    assert grown.version == 2 and grown.terms == ('INSERT OR IGNORE', 'dedup')


@pytest.mark.parametrize('payload', [
    {**STATE, 'goal': ''}, {**STATE, 'goal': None}, {**STATE, 'constraints': 'одна строка'},
    {**STATE, 'clarified': ['', 'x']}, {**STATE, 'terms': ['x' * 400]}, 'not a dict',
    {**STATE, 'constraints': [f'пункт {i}' for i in range(41)]},
])
def test_normalize_state_rejects_invalid(payload):
    with pytest.raises(ValueError):
        ts.normalize_state('s1', payload, None)


def test_append_only_merge_is_enforced_in_code():
    state = ts.normalize_state('s1', STATE, None)
    # The model dropped and reformulated recorded items; the merge keeps them.
    candidate = ts.normalize_state('s1', {'goal': 'Новая формулировка цели', 'clarified': ['новое уточнение'],
                                          'constraints': ['новое ограничение'], 'terms': ['dedup']}, state)
    merged = ts.merge_state(state, candidate)
    assert merged.goal == state.goal and merged.version == 2
    assert merged.constraints == ('только стандартная библиотека', 'новое ограничение')
    assert merged.terms == ('INSERT OR IGNORE', 'dedup')
    assert 'интересует День 18' in merged.clarified and 'новое уточнение' in merged.clarified
    with pytest.raises(ValueError, match='пунктов'):
        ts.merge_state(state, ts.normalize_state('s1', {**STATE, 'terms': [f't{i}' for i in range(41)]}, None))


def test_merge_first_state_is_candidate():
    candidate = ts.normalize_state('s1', STATE, None)
    assert ts.merge_state(None, candidate) == candidate


def test_store_versions_and_events(tmp_path):
    store = ts.TaskStateStore(tmp_path)
    first = store.create('s1')
    assert first.version == 0
    state = ts.normalize_state('s1', STATE, None)
    saved = store.save(state, previous_version=0, event='created')
    assert saved.version == 1 and store.get('s1').constraints == ('только стандартная библиотека',)
    with pytest.raises(ValueError, match='устарело'):
        store.save(ts.normalize_state('s1', {**STATE, 'terms': ['INSERT OR IGNORE', 'x']}, saved),
                   previous_version=0, event='stale')
    assert [e['event'] for e in store.events('s1')] == ['created']


# ---------------------------------------------------------------- chat store

def test_chat_store_roundtrip_and_resume(tmp_path):
    store = cs.ChatStore(tmp_path)
    session = store.create_session()
    assert store.session_exists(session) and not store.session_exists('missing')
    store.append(session, 'user', 'Вопрос')
    store.append(session, 'assistant', 'Ответ', payload={'turn': 1})
    with pytest.raises(ValueError):
        store.append(session, 'system', 'x')
    history = store.history(session)
    assert [h['role'] for h in history] == ['user', 'assistant']
    assert history[1]['payload'] == {'turn': 1}
    assert len(store.history(session, limit=1)) == 1
    assert store.sessions()[0]['messages'] == 2
    # A new store instance over the same directory resumes the same session.
    reopened = cs.ChatStore(tmp_path)
    assert reopened.session_exists(session) and len(reopened.history(session)) == 2


# ---------------------------------------------------------------- chat agent

def test_turn_attaches_sources_and_updates_state(tmp_path):
    llm = FakeLLM(['Как дедупликация защищает RSS от повторной обработки?', STATE])
    a = agent(tmp_path, [], [rag_result()])
    a.llm = llm
    session = a.create_session()
    result = a.turn(session, 'Как защищаются от повторной обработки статей в Дне 18?')
    assert result['status'] == 'answered' and result['sources'] and result['quotes']
    assert result['search_query'] == 'Как дедупликация защищает RSS от повторной обработки?'
    assert result['task_state']['version'] == 1
    assert result['task_state']['constraints'] == ('только стандартная библиотека',)
    assert not result['state_errors']
    # The user message and the assistant payload are persisted for resume.
    stored = a.chats.history(session)
    assert [h['role'] for h in stored] == ['user', 'assistant']
    assert stored[1]['payload']['sources']
    view = a.session(session)
    assert view['task_state']['goal'] == STATE['goal'] and view['state_events'][0]['event'] == 'created'


def test_turn_unknown_has_no_sources(tmp_path):
    a = agent(tmp_path, [STATE], [rag_result(status='unknown', answer='Не знаю. Уточните вопрос.')])
    a.condense_query = lambda message, history, state: (message, False)
    session = a.create_session()
    result = a.turn(session, 'Какой пароль администратора?')
    assert result['status'] == 'unknown' and not result['sources'] and not result['quotes']
    assert result['task_state']['goal']


def test_state_update_survives_bad_model_output(tmp_path):
    llm = FakeLLM(['not json', {**STATE, 'constraints': []}])
    a = agent(tmp_path, [], [rag_result(), rag_result()])
    a.llm = llm
    a.condense_query = lambda message, history, state: (message, True)
    session = a.create_session()
    first = a.turn(session, 'Разбираю дедупликацию Дня 18. Только стандартная библиотека.')
    assert first['task_state']['version'] == 1
    second = a.turn(session, 'Что происходит при повторной вставке?')
    # Both attempts failed validation: the previous state is kept, not corrupted.
    assert second['task_state'] == first['task_state'] and len(second['state_errors']) == 2
    assert len(a.llm.calls) == 4  # two state attempts per turn, condense disabled by injection


def test_condense_fallback_on_llm_failure(tmp_path):
    a = agent(tmp_path, [], [rag_result(), rag_result()])
    a.llm = FakeLLM([STATE])
    a.condense_query = lambda message, history, state: (message, True)
    session = a.create_session()
    result = a.turn(session, 'Вопрос без переформулировки')
    assert result['condense_fallback'] and result['search_query'] == 'Вопрос без переформулировки'


def test_message_validation_and_unknown_session(tmp_path):
    a = agent(tmp_path, [], [])
    with pytest.raises(ValueError):
        a.turn('missing', 'Вопрос')
    session = a.create_session()
    with pytest.raises(ValueError):
        a.turn(session, '   ')
    with pytest.raises(ValueError):
        a.turn(session, 'x' * 1001)
    with pytest.raises(ValueError):
        a.session('missing')


def test_memory_reaches_generation_without_becoming_evidence():
    client = FakeLLM(['answer', 'verdict'])
    state = ts.normalize_state('s1', STATE, None)
    wrapped = ca.MemoryClient(client, 'Итог с учётом ограничений', state)
    wrapped.call('КОНТЕКСТ: код', system_instruction=ca.day24.SYSTEM)
    wrapped.call('Цитаты для проверки', system_instruction=ca.day24.VERIFY_SYSTEM)
    assert STATE['constraints'][0] in client.calls[0]
    assert STATE['goal'] in client.calls[0] and 'Итог с учётом ограничений' in client.calls[0]
    assert client.calls[1] == 'Цитаты для проверки'


def test_implementation_search_does_not_use_predevelopment_plan(monkeypatch):
    chunks = [SimpleNamespace(source='day19/PLAN.md'), SimpleNamespace(source='day19/pipeline.py')]
    monkeypatch.setattr(ca.day24.RagAgent, 'retrieve', lambda *args, **kwargs: chunks)
    rag = ca.ChatRag.__new__(ca.ChatRag)
    assert [c.source for c in rag.retrieve('Как передаются данные?', top_k=16)] == ['day19/pipeline.py']
    assert len(rag.retrieve('Что описывает план?', top_k=16)) == 2


def test_provider_failure_keeps_answer_and_previous_memory(tmp_path):
    a = agent(tmp_path, [STATE], [rag_result(), rag_result()])
    a.condense_query = lambda message, history, state: (message, False)
    session = a.create_session()
    first = a.turn(session, 'Цель: разобраться в RSS')
    class BrokenClient:
        def call(self, *args, **kwargs):
            raise RuntimeError('Provider unavailable')
    a.llm = BrokenClient()
    second = a.turn(session, 'Уточнение')
    assert second['task_state'] == first['task_state']
    assert second['status'] == 'answered' and second['sources']
    assert len(second['state_errors']) == 2
    assert len(a.chats.history(session)) == 4


def test_failed_history_write_rolls_back_state(tmp_path):
    a = agent(tmp_path, [STATE], [rag_result()])
    a.condense_query = lambda message, history, state: (message, False)
    session = a.create_session()
    with sqlite3.connect(a.chats.path) as conn:
        conn.execute("CREATE TRIGGER fail_assistant BEFORE INSERT ON messages "
                     "WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        a.turn(session, 'Вопрос')
    assert a.states.get(session).version == 0
    assert a.chats.history(session) == [] and a.states.events(session) == []


def test_resume_keeps_goal_constraints_and_sources(tmp_path):
    a = agent(tmp_path, [STATE], [rag_result()])
    a.condense_query = lambda message, history, state: (message, False)
    session = a.create_session()
    a.turn(session, 'Вопрос')
    reopened = agent(tmp_path, [], [])
    view = reopened.session(session)
    assert view['task_state']['goal'] == STATE['goal']
    assert view['task_state']['constraints'] == (STATE['constraints'][0],)
    assert view['history'][1]['payload']['sources'][0]['source'] == 'feed_store.py'


@pytest.mark.parametrize('answer,valid', [('INSERT OR IGNORE', True), ('url TEXT PRIMARY KEY', True), ('Повторы возможны', False)])
def test_evaluation_accepts_both_dedup_mechanisms_and_rejects_unrelated_answer(answer, valid):
    evaluator = load('day25_evaluator', DAY / 'evaluate.py')
    checks = evaluator.audit_turn(rag_result(answer=answer, state_errors=[]),
        {'status': 'answered', 'required_any_terms': ['INSERT OR IGNORE', 'PRIMARY KEY']})
    assert checks['required_mechanism'] is valid


# -------------------------------------------------------------------- web api

def test_web_api(tmp_path):
    server_module = load('day25_server', DAY / 'web_server.py')
    llm = FakeLLM(['Поиск по Дню 18', STATE])
    fake = agent(tmp_path, [], [rag_result()])
    fake.llm = llm
    server = server_module.create_server(agent=fake, data_dir=tmp_path / 'webdata')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        def post(path, payload):
            request = urllib.request.Request(url + path, data=json.dumps(payload).encode(),
                                             headers={'Content-Type': 'application/json', 'Origin': url})
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        created = post('/api/session', {})
        session = created['session_id']
        assert created['history'] == [] and created['task_state']['version'] == 0
        # The UI posts without a body; the server must accept it too.
        empty = urllib.request.urlopen(urllib.request.Request(url + '/api/session', data=b'',
                                                              headers={'Origin': url}))
        assert json.load(empty)['session_id']
        turn = post('/api/chat', {'session_id': session, 'message': 'Как устроена дедупликация в Дне 18?'})
        assert turn['status'] == 'answered' and turn['sources']
        restored = json.load(urllib.request.urlopen(f'{url}/api/session?id={session}'))
        assert restored['task_state']['goal'] == STATE['goal'] and len(restored['history']) == 2
        state = json.load(urllib.request.urlopen(url + '/api/state'))
        assert any(s['session_id'] == session and s['messages'] == 2 for s in state['sessions'])
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            post('/api/chat', {'session_id': 'missing', 'message': 'Вопрос'})
        assert excinfo.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
