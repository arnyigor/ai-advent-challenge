"""Тесты дня 34: sandbox файловых инструментов, агентный цикл, веб-API.

Логика инструментов тестируется как чистые функции; сквозной агентный цикл —
через настоящий MCP stdio-процесс и подставную модель без LLM."""
import asyncio
from contextlib import contextmanager
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DAY = ROOT / 'day34-file-assistant'

@contextmanager
def day34_imports(modules=None):
    """Keep this day's generic module names out of other days' import state."""
    names = ('agent', 'mcp_client', 'model_provider', 'files_mcp_server', 'server')
    saved = {name: sys.modules.get(name) for name in names}
    old_path = sys.path[:]
    try:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(modules or {})
        sys.path.insert(0, str(DAY))
        yield
    finally:
        sys.path[:] = old_path
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


with day34_imports():
    agent = importlib.import_module('agent')
    fms = importlib.import_module('files_mcp_server')
    client_module = importlib.import_module('mcp_client')
    provider_module = importlib.import_module('model_provider')
    FileToolSession = client_module.FileToolSession


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'proj'
    (root / 'src').mkdir(parents=True)
    (root / 'docs').mkdir()
    (root / 'src' / 'a.py').write_text('class Foo:\n    pass\n\nfoo = Foo()\n', encoding='utf-8')
    (root / 'src' / 'b.py').write_text('from a import Foo\n\nbar = Foo()\n', encoding='utf-8')
    (root / 'README.md').write_text('# Проект\n\nИспользуй Foo.\n', encoding='utf-8')
    (root / 'docs' / 'notes.md').write_text('заметки\n', encoding='utf-8')
    (root / '.env').write_text('TOKEN=x\n', encoding='utf-8')
    (root / 'secret.pem').write_text('-----BEGIN-----\n', encoding='utf-8')
    (root / 'bin.dat').write_bytes(b'\x00\x01\x02')
    return root


@pytest.fixture
def baseline(tmp_path, project):
    base = tmp_path / 'base'
    import shutil
    shutil.copytree(project, base)
    return base


# --- sandbox ---

def test_resolve_rejects_traversal(project):
    with pytest.raises(ValueError):
        fms.resolve_path(project, '../outside.txt')
    with pytest.raises(ValueError):
        fms.resolve_path(project, 'src/../../outside.txt')


def test_resolve_rejects_absolute(project):
    with pytest.raises(ValueError):
        fms.resolve_path(project, 'C:/Windows/win.ini')
    with pytest.raises(ValueError):
        fms.resolve_path(project, '/etc/passwd')


def test_resolve_rejects_secrets_and_hidden(project):
    for bad in ('.env', '.git/config', 'secret.pem', 'src/.hidden', 'id_rsa'):
        with pytest.raises(ValueError):
            fms.resolve_path(project, bad)


def test_resolve_allows_normal(project):
    assert fms.resolve_path(project, 'src/a.py') == (project / 'src' / 'a.py').resolve()


def test_read_binary_rejected(project):
    with pytest.raises(ValueError, match='бинарный'):
        fms.tool_read_file(project, 'bin.dat')


# --- чтение и поиск ---

def test_read_file_numbering_and_range(project):
    result = fms.tool_read_file(project, 'src/a.py', 2, 3)
    assert result['total_lines'] == 4
    assert '2:     pass' in result['content']
    assert result['shown_lines'] == [2, 3]


def test_read_file_missing(project):
    with pytest.raises(ValueError, match='не найден'):
        fms.tool_read_file(project, 'src/none.py')


def test_search_files_regex_across_files(project):
    result = fms.tool_search_files(project, r'Foo\(\)')
    paths = {m['path'] for m in result['matches']}
    assert paths == {'src/a.py', 'src/b.py'}
    assert all(m['line'] > 0 for m in result['matches'])


def test_search_files_glob_and_cap(project):
    result = fms.tool_search_files(project, 'Foo', file_glob='docs/*.md', max_results=5)
    assert result['matches'] == []  # в docs нет упоминаний Foo
    result = fms.tool_search_files(project, 'Foo', file_glob='**/*.md')
    assert [m['path'] for m in result['matches']] == ['README.md']
    result = fms.tool_search_files(project, 'Foo', max_results=1)
    assert len(result['matches']) == 1 and result['truncated']


def test_search_files_invalid_regex(project):
    with pytest.raises(ValueError, match='регулярное'):
        fms.tool_search_files(project, '([')


def test_list_files_skips_denied(project):
    names = {f['path'] for f in fms.tool_list_files(project)['files']}
    assert 'src/a.py' in names and '.env' not in names and 'secret.pem' not in names


# --- запись и diff ---

def test_write_file_creates_with_diff(project):
    result = fms.tool_write_file(project, 'docs/new.md', '# Новый\n')
    assert result['created'] and '+# Новый' in result['diff']
    assert (project / 'docs' / 'new.md').read_text(encoding='utf-8') == '# Новый\n'


def test_write_file_overwrite_diff(project):
    result = fms.tool_write_file(project, 'README.md', '# Проект v2\n')
    assert not result['created']
    assert '-# Проект' in result['diff'] and '+# Проект v2' in result['diff']


def test_write_file_size_limit(project):
    with pytest.raises(ValueError, match='100 КБ'):
        fms.tool_write_file(project, 'big.txt', 'x' * (fms.MAX_WRITE + 1))


def test_replace_in_file_exact_count(project):
    result = fms.tool_replace_in_file(project, 'src/a.py', 'foo = Foo()', 'foo = Foo()  # main')
    assert result['replacements'] == 1
    assert '# main' in (project / 'src' / 'a.py').read_text(encoding='utf-8')
    assert '+' in result['diff']


def test_replace_in_file_count_mismatch(project):
    with pytest.raises(ValueError, match='вхождений'):
        fms.tool_replace_in_file(project, 'src/a.py', 'Foo', 'Bar')  # найдено 2, ожидалось 1
    ok = fms.tool_replace_in_file(project, 'src/a.py', 'Foo', 'Bar', count=2)
    assert ok['replacements'] == 2


def test_replace_in_file_not_found(project):
    with pytest.raises(ValueError, match='не найден'):
        fms.tool_replace_in_file(project, 'src/a.py', 'нет такого', 'x')


def test_write_normalizes_crlf(project):
    fms.tool_write_file(project, 'docs/crlf.md', 'a\r\nb\r\n')
    data = (project / 'docs' / 'crlf.md').read_bytes()
    assert b'\r' not in data
    result = fms.tool_replace_in_file(project, 'docs/crlf.md', 'b\n', 'c\r\n')
    assert (project / 'docs' / 'crlf.md').read_bytes() == b'a\nc\n'
    assert '-b' in result['diff'] and '+c' in result['diff']


def test_session_diff_lists_changes(project, baseline):
    fms.tool_replace_in_file(project, 'README.md', 'Используй Foo.', 'Используй Foo и Bar.')
    fms.tool_write_file(project, 'docs/extra.md', 'новое\n')
    result = fms.tool_session_diff(project, baseline)
    assert set(result['changed_files']) == {'README.md', 'docs/extra.md'}
    assert '+Используй Foo и Bar.' in result['diff'] and '+новое' in result['diff']


# --- протокол шагов ---

def test_parse_step_plain_and_fenced():
    step = agent.parse_step('{"action": "tool", "name": "list_files", "arguments": {}}')
    assert step['name'] == 'list_files'
    fenced = 'Вот шаг:\n```json\n{"action": "final", "answer": "готово"}\n```'
    assert agent.parse_step(fenced)['answer'] == 'готово'


def test_parse_step_rejects_garbage():
    for bad in ('', 'не json', '{"action": "noop"}', '{"action": "tool"}',
                '{"action": "final", "answer": ""}'):
        with pytest.raises(ValueError):
            agent.parse_step(bad)


# --- агентный цикл через настоящий MCP ---

class ScriptedModel:
    label = 'fake:scripted'

    def __init__(self, script):
        self.script = list(script)

    def generate(self, system, prompt):
        assert self.script, 'скрипт модели исчерпан'
        return {'answer': self.script.pop(0)}


def _step(action, **fields):
    return json.dumps({'action': action, **fields}, ensure_ascii=False)


def test_agent_full_loop_real_mcp(project, baseline):
    model = ScriptedModel([
        _step('tool', name='search_files', arguments={'query': 'Foo'}, thought='ищу'),
        _step('tool', name='replace_in_file',
              arguments={'path': 'README.md', 'old': 'Используй Foo.', 'new': 'Используй Foo и Bar.'},
              thought='правлю'),
        _step('final', answer='Обновил README по коду.'),
    ])
    result = asyncio.run(agent.run_agent('обнови README', model=model,
        session=FileToolSession(project, baseline)))
    assert result['answer'] == 'Обновил README по коду.'
    assert result['tool_calls'] == 2
    assert result['changed_files'] == ['README.md']
    assert '+Используй Foo и Bar.' in result['diff']
    assert result['mcp_server'] == 'day34-files'
    assert (project / 'README.md').read_text(encoding='utf-8').count('Bar') == 1


def test_agent_recovers_from_protocol_error(project, baseline):
    model = ScriptedModel([
        'сейчас подумаю…',  # невалидный шаг → замечание в транскрипт
        _step('final', answer='Хорошо, отвечаю по протоколу.'),
    ])
    result = asyncio.run(agent.run_agent('привет', model=model,
        session=FileToolSession(project, baseline)))
    assert 'протоколу' in result['answer']


def test_agent_fails_after_repeated_protocol_errors(project, baseline):
    model = ScriptedModel(['мусор'] * 10)
    with pytest.raises(RuntimeError, match='протоколу'):
        asyncio.run(agent.run_agent('привет', model=model,
            session=FileToolSession(project, baseline)))


def test_agent_tool_error_is_fed_back(project, baseline):
    model = ScriptedModel([
        _step('tool', name='read_file', arguments={'path': 'нет/такого.md'}, thought='читаю'),
        _step('final', answer='Файла нет, честно сообщаю.'),
    ])
    result = asyncio.run(agent.run_agent('прочитай несуществующее', model=model,
        session=FileToolSession(project, baseline)))
    assert result['steps'][0]['error']
    assert 'нет' in result['answer']


def test_agent_step_limit(project, baseline):
    model = ScriptedModel([_step('tool', name='list_files', arguments={}, thought='x')] * 20)
    with pytest.raises(RuntimeError, match='шагов'):
        asyncio.run(agent.run_agent('бесконечный цикл', model=model, max_steps=3,
            session=FileToolSession(project, baseline)))


def test_agent_unknown_tool_rejected(project, baseline):
    model = ScriptedModel([
        _step('tool', name='delete_everything', arguments={}, thought='хочу удалить'),
        _step('final', answer='Инструмента удаления нет.'),
    ])
    result = asyncio.run(agent.run_agent('удали всё', model=model,
        session=FileToolSession(project, baseline)))
    assert 'неизвестный инструмент' in result['steps'][0]['error']


def test_reset_project(project, baseline):
    fms.tool_write_file(project, 'changed.txt', 'x\n')
    result = agent.reset_project(project, baseline)
    assert result['reset'] and not (project / 'changed.txt').exists()
    assert (project / 'src' / 'a.py').exists()


# --- веб-API ---

@pytest.fixture
def client(tmp_path, monkeypatch):
    proj = tmp_path / 'proj'
    base = tmp_path / 'base'
    import shutil
    shutil.copytree(DAY / 'baseline', base)
    shutil.copytree(DAY / 'baseline', proj)
    monkeypatch.setenv('DAY34_PROJECT_ROOT', str(proj))
    monkeypatch.setenv('DAY34_BASELINE_ROOT', str(base))
    monkeypatch.setattr(agent, 'DAY', DAY)
    with day34_imports({'agent': agent, 'mcp_client': client_module,
                        'model_provider': provider_module, 'files_mcp_server': fms}):
        server = importlib.import_module('server')
    from fastapi.testclient import TestClient
    with TestClient(server.app) as test_client:
        yield test_client, server


def test_api_bootstrap_and_reset(client):
    test_client, server = client
    data = test_client.get('/api/bootstrap').json()
    assert data['mcp']['server'] == 'day34-files'
    assert len(data['mcp']['tools']) == 6
    assert len(data['scenarios']) == 3
    assert test_client.get('/healthz').json()['ok'] is True
    reset = test_client.post('/api/reset').json()
    assert reset['reset'] and 'README.md' in reset['files']


def test_api_runs_validation_and_lookup(client):
    test_client, server = client
    assert test_client.post('/api/runs', json={'goal': ''}).status_code == 422
    assert test_client.get('/api/runs/nope').status_code == 404


def test_api_run_with_scripted_model(client, monkeypatch):
    test_client, server = client
    monkeypatch.setattr(agent, 'create_model', lambda: ScriptedModel([
        _step('tool', name='list_files', arguments={}, thought='смотрю'),
        _step('final', answer='Список получен.'),
    ]))
    run_id = test_client.post('/api/runs', json={'goal': 'покажи файлы'}).json()['run_id']
    for _ in range(50):
        run = test_client.get(f'/api/runs/{run_id}').json()
        if run['status'] != 'running':
            break
        import time
        time.sleep(0.2)
    assert run['status'] == 'done'
    assert run['tool_calls'] == 1 and run['answer'] == 'Список получен.'
    assert run['steps'][0]['tool'] == 'list_files'

# --- регрессии аудита ---

def test_read_explicit_range_still_capped(project):
    (project / 'long.txt').write_text('line\n' * 600, encoding='utf-8')
    result = fms.tool_read_file(project, 'long.txt', 1, 600)
    assert result['shown_lines'] == [1, 400]
    assert result['truncated']
    with pytest.raises(ValueError, match='end_line'):
        fms.tool_read_file(project, 'long.txt', 10, 2)


def test_write_does_not_overwrite_binary_or_large(project):
    with pytest.raises(ValueError, match='бинарный'):
        fms.tool_write_file(project, 'bin.dat', 'replacement')
    assert (project / 'bin.dat').read_bytes() == b'\x00\x01\x02'
    (project / 'large.txt').write_bytes(b'a' * (fms.MAX_FILE + 1))
    with pytest.raises(ValueError, match='200 КБ'):
        fms.tool_write_file(project, 'large.txt', 'replacement')


def test_mcp_search_respects_result_limit(project, baseline):
    async def check():
        async with FileToolSession(project, baseline) as session:
            result = await session.call('search_files', {'query': 'Foo', 'max_results': 1})
            assert len(result['matches']) == 1
    asyncio.run(check())


def test_agent_diff_includes_edit_after_model_diff(project, baseline):
    model = ScriptedModel([
        _step('tool', name='session_diff', arguments={}),
        _step('tool', name='write_file', arguments={'path': 'new.md', 'content': 'new\n'}),
        _step('final', answer='Готово.'),
    ])
    result = asyncio.run(agent.run_agent('создай файл', model=model,
        session=FileToolSession(project, baseline)))
    assert result['changed_files'] == ['new.md']
    assert '+new' in result['diff']


@pytest.mark.parametrize('target', ['same', 'parent', 'child'])
def test_reset_rejects_overlapping_roots(tmp_path, target):
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'keep.txt').write_text('keep', encoding='utf-8')
    project = {'same': base, 'parent': tmp_path, 'child': base / 'child'}[target]
    with pytest.raises(ValueError, match='небезопасный'):
        agent.reset_project(project, base)
    assert (base / 'keep.txt').read_text(encoding='utf-8') == 'keep'

@pytest.mark.parametrize('path', ['README.md:stream', 'src/a.py:payload'])
def test_windows_alternate_stream_rejected(project, path):
    with pytest.raises(ValueError):
        fms.resolve_path(project, path)


def test_api_preserves_diff_when_model_fails(client, monkeypatch):
    test_client, server = client
    class FailingModel(ScriptedModel):
        def generate(self, system, prompt):
            if not self.script:
                raise RuntimeError('generation connection lost')
            return super().generate(system, prompt)
    monkeypatch.setattr(agent, 'create_model', lambda: FailingModel([
        _step('tool', name='write_file', arguments={'path': 'created.md', 'content': 'saved\n'}),
    ]))
    run_id = test_client.post('/api/runs', json={'goal': 'создай документ'}).json()['run_id']
    for _ in range(50):
        run = test_client.get(f'/api/runs/{run_id}').json()
        if run['status'] != 'running':
            break
        import time
        time.sleep(0.2)
    assert run['status'] == 'error'
    assert 'connection lost' in run['error']
    assert run['changed_files'] == ['created.md']
    assert '+saved' in run['diff']
