"""Day 31 contracts, including an actual stdio MCP exchange with temporary Git."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.error import HTTPError
import urllib.request

import pytest

DAY = Path(__file__).resolve().parents[1] / 'day31-developer-assistant'
sys.path.insert(0, str(DAY))
from assistant import Assistant, DEFAULT_QUESTION, parse_command
from project_context import get_context
from project_index import ProjectPipeline, StaleIndexError, corpus, inspect_index
from chunkers import chunk_documents
from embeddings import HashEmbedder
from index_store import write_index
import importlib.util

# Other days use a generic server.py; load this server by a unique module name.
spec = importlib.util.spec_from_file_location('day31_http_server', DAY / 'server.py')
http_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http_module)


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'README.md').write_text('# Project\nProject structure is in docs.\n', encoding='utf-8')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs' / 'architecture.md').write_text('# Structure\nRAG is in day31.\n', encoding='utf-8')
    return tmp_path


@pytest.fixture
def pipeline(project):
    embedder = HashEmbedder()  # Unit tests only; real acceptance uses E5.
    docs = corpus(project)
    chunks = chunk_documents(docs, 'structure', 1000)
    index = project / 'index.sqlite3'
    write_index(index, docs, chunks, embedder.encode_documents([c.text for c in chunks]),
                embedding_model=embedder.name, embedding_dim=embedder.dimension, chunk_size=1000)
    return ProjectPipeline(index=index, root=project, embedder=embedder)


def test_command_default_and_question():
    assert parse_command(' /help ') == DEFAULT_QUESTION
    assert parse_command('/help Какая ветка?') == 'Какая ветка?'


@pytest.mark.parametrize('value', [None, {}, '', '/helpful', '/index', '/help ' + 'x' * 1001])
def test_invalid_commands(value):
    with pytest.raises(ValueError):
        parse_command(value)


def test_corpus_allowlist(project):
    (project / '.env').write_text('fake-secret-not-to-index', encoding='utf-8')
    (project / 'unlisted.md').write_text('not in corpus', encoding='utf-8')
    assert [d.source for d in corpus(project)] == ['README.md', 'docs/architecture.md']


@pytest.mark.parametrize('change', ['edit', 'add', 'remove'])
def test_freshness(pipeline, project, change):
    pipeline.assert_fresh()
    path = project / 'docs' / 'architecture.md'
    if change == 'edit':
        path.write_text('Changed documentation', encoding='utf-8')
    elif change == 'add':
        (project / 'docs' / 'api.md').write_text('# API', encoding='utf-8')
    else:
        # Rename within temporary fixture to simulate removal without deleting data.
        path.rename(project / 'architecture.saved')
        (project / 'docs' / 'other.md').write_text('# Other', encoding='utf-8')
    with pytest.raises(StaleIndexError):
        pipeline.assert_fresh()


def test_inspect_does_not_load_model(pipeline):
    assert inspect_index(pipeline.index)['documents'] == 2


def test_prepare_includes_real_context_and_sources(pipeline):
    async def context(root):
        return {'project': {'branch': 'test-live'}, 'mcp': {'steps': ['tools/call']}}
    result = Assistant(pipeline, context).help('/help structure', retrieve_only=True)
    assert result['project']['branch'] == 'test-live'
    assert 'test-live' in result['prompt']
    assert result['sources']


def test_mcp_error_is_not_model_answer(pipeline):
    async def unavailable(root):
        raise RuntimeError('MCP unavailable')
    with pytest.raises(RuntimeError, match='MCP unavailable'):
        Assistant(pipeline, unavailable).help('/help')


def test_current_api_scope_excludes_other_days_and_named_day_is_searchable(project):
    historical = project / 'day24-other-api'
    historical.mkdir()
    (historical / 'README.md').write_text('# API\nAPI fields model_output semantic_check.\n', encoding='utf-8')
    (project / 'docs' / 'api.md').write_text('# API\nAPI fields question answer project.\n', encoding='utf-8')
    embedder = HashEmbedder()
    docs = corpus(project)
    chunks = chunk_documents(docs, 'structure', 1000)
    index = project / 'scoped.sqlite3'
    write_index(index, docs, chunks, embedder.encode_documents([c.text for c in chunks]),
                embedding_model=embedder.name, embedding_dim=embedder.dimension, chunk_size=1000)
    scoped = ProjectPipeline(index=index, root=project, embedder=embedder)
    current = scoped.prepare('API fields')
    assert all(not s['source'].startswith('day24-') for s in current['sources'])
    named = scoped.prepare('API fields дня 24')
    assert any(s['source'].startswith('day24-') for s in named['sources'])


def test_real_mcp_branch_changes_and_detached(project):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(project), *args], encoding='utf-8').strip()
    git('init', '-b', 'initial')
    git('add', 'README.md', 'docs/architecture.md')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
    first = asyncio.run(get_context(project))
    assert first['project']['branch'] == 'initial'
    assert first['mcp']['steps'] == ['initialize', 'tools/list', 'tools/call']
    assert first['mcp']['tool'] == 'get_project_context'
    git('switch', '-c', 'next')
    assert asyncio.run(get_context(project))['project']['branch'] == 'next'
    git('checkout', '--detach')
    detached = asyncio.run(get_context(project))['project']
    assert detached['detached'] and detached['branch'] == '(detached HEAD)'
    assert detached['head'] == git('rev-parse', 'HEAD')


def test_mcp_non_repository_reports_error(project):
    with pytest.raises(Exception):
        asyncio.run(get_context(project))


@contextmanager
def running_server(service):
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(('127.0.0.1', 0), http_module.make_handler(service))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def post(url, body, headers=None):
    req = urllib.request.Request(url + '/api/help', data=body,
        headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def test_http_validation_and_origin(pipeline):
    with running_server(Assistant(pipeline)) as url:
        assert post(url, b'[]')[0] == 400
        assert post(url, b'{')[0] == 400
        assert post(url, b'{"command":"/bad"}')[0] == 400
        assert post(url, b'x' * 8193)[0] == 413
        assert post(url, b'{}', {'Origin': 'http://evil.invalid'})[0] == 403


def test_http_stale_and_backend_error(pipeline, project):
    async def broken(root):
        raise RuntimeError('provider-sensitive-detail')
    with running_server(Assistant(pipeline, broken)) as url:
        status, body = post(url, b'{"command":"/help"}')
        assert status == 502 and 'provider-sensitive-detail' not in body['error']
        (project / 'README.md').write_text('changed', encoding='utf-8')
        assert post(url, b'{"command":"/help"}')[0] == 409


def test_http_busy_and_result(pipeline):
    started, release = threading.Event(), threading.Event()

    class SlowService:
        def help(self, command):
            started.set()
            assert release.wait(4)
            return {'answer': 'result', 'prompt': 'internal'}

    service = SlowService()
    service.pipeline = pipeline
    with running_server(service) as url, ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(post, url, b'{"command":"/help"}')
        assert started.wait(2)
        assert post(url, b'{"command":"/help"}')[0] == 409
        release.set()
        status, body = request.result()
        assert status == 200 and body == {'answer': 'result'}
