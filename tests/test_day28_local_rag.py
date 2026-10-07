"""No real embedding or generation model is used by these tests."""
import importlib.util
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.error

import pytest

DAY = Path(__file__).resolve().parents[1] / 'day28-local-rag'
sys.path.insert(0, str(DAY))
spec = importlib.util.spec_from_file_location('day28_rag', DAY / 'rag.py')
rag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rag)
from embeddings import HashEmbedder
from index_store import write_index
from models import Document, Chunk


def load_day28(name):
    spec = importlib.util.spec_from_file_location('day28_' + name, DAY / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pipeline(tmp_path):
    embedder = HashEmbedder()
    document = Document('rss.py', 'RSS', 'rss.py', 'ru', 'INSERT OR IGNORE предотвращает дубли RSS.', 'hash')
    chunk = Chunk('c1', document.source, 'RSS', 'rss.py', 'Хранение', 'structure', 0, 0,
                  len(document.text), document.text, 'hash', 'ru')
    path = tmp_path / 'index.sqlite3'
    write_index(path, [document], [chunk], embedder.encode_documents([chunk.text]),
                embedding_model=embedder.name, embedding_dim=embedder.dimension, chunk_size=1200)
    return rag.Pipeline(path, embedder=embedder)


class FakeModel:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return dict(answer='Дубли предотвращает INSERT OR IGNORE [1]', model='fake', finish_reason='stop')


def test_retrieval_and_answer(pipeline):
    model = FakeModel()
    before = pipeline.index.read_bytes()
    prepared = pipeline.prepare('Как предотвращают дубли RSS?')
    assert not model.prompts
    assert prepared['sources'][0]['chunk_id'] == 'c1'
    result = pipeline.answer(prepared, model)
    assert result['citation_ids_valid'] and result['has_citations']
    assert 'INSERT OR IGNORE' in model.prompts[0]
    assert pipeline.index.read_bytes() == before


def test_identity_and_validation(pipeline):
    for question in ('', 'a' * 1001, None):
        with pytest.raises(ValueError):
            pipeline.prepare(question)
    pipeline.embedder.name = 'another-384'
    with pytest.raises(ValueError, match='identity'):
        pipeline.prepare('RSS')


def test_invalid_citations(pipeline):
    model = FakeModel()
    model.generate = lambda _: dict(answer='Факт [99]', model='fake')
    assert not pipeline.answer(pipeline.prepare('RSS'), model)['citation_ids_valid']


def test_refusal_without_citations_is_explicit(pipeline):
    model = FakeModel()
    model.generate = lambda _: dict(answer='В найденных документах недостаточно данных.', model='fake')
    result = pipeline.answer(pipeline.prepare('RSS'), model)
    assert result['answer_status'] == 'unknown'
    assert not result['has_citations']
    assert result['citation_ids_valid']


def test_hybrid_excludes_plans_but_allows_explicit_plan(tmp_path):
    embedder = HashEmbedder()
    documents = [Document(source, 'RSS', source, 'ru', 'RSS dedup INSERT OR IGNORE', source)
                 for source in ('day/PLAN.md', 'day/code.py')]
    chunks = [Chunk(str(i), d.source, d.title, d.file, 'module', 'structure', 0, 0,
                    len(d.text), d.text, d.content_hash, 'ru') for i,d in enumerate(documents)]
    index = tmp_path/'index.sqlite3'
    write_index(index, documents, chunks, embedder.encode_documents([c.text for c in chunks]),
                embedding_model=embedder.name, embedding_dim=embedder.dimension, chunk_size=1200)
    pipeline = rag.Pipeline(index, embedder=embedder)
    assert all(s['source'] != 'day/PLAN.md' for s in pipeline.prepare('RSS dedup')['sources'])
    assert any(s['source'] == 'day/PLAN.md' for s in pipeline.prepare('План RSS dedup')['sources'])


@pytest.mark.parametrize('url', ['https://127.0.0.1/v1', 'http://localhost/v1',
    'http://example.com/v1', 'http://127.0.0.1@evil.com/v1', 'http://127.0.0.1/v1?x=1'])
def test_reject_non_loopback(url):
    with pytest.raises(ValueError):
        rag.LocalModel(url, 'test')


def test_http_client_contract():
    state = {'response': {'choices': [{'message': {'content': 'ответ [1]'}, 'finish_reason': 'length'}]}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state['request'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if state.get('redirect'):
                self.send_response(302)
                self.send_header('Location', 'http://example.com/')
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(state['response']).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        model = rag.LocalModel(f'http://127.0.0.1:{server.server_port}/v1', 'fake')
        assert model.generate('context')['finish_reason'] == 'length'
        assert state['request']['messages'][0]['content'] == rag.SYSTEM
        assert state['request']['messages'][1]['content'] == 'context'
        state['response']['choices'][0]['message']['content'] = ''
        with pytest.raises(RuntimeError, match='empty'):
            model.generate('test')
        state['redirect'] = True
        with pytest.raises(RuntimeError, match='Redirect'):
            model.generate('test')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_benchmark_same_context_and_errors(pipeline):
    evaluate = load_day28('evaluate')
    local, cloud = FakeModel(), FakeModel()
    report = evaluate.benchmark(pipeline, [{'query': 'RSS', 'relevant_sources': ['rss.py']}],
                                {'local': local, 'cloud': cloud}, 2)
    assert local.prompts == cloud.prompts
    assert len({r['prompt_sha256'] for r in report['runs']}) == 1
    assert report['summary']['local']['success_rate'] == 1
    assert all(r['manual_quality'] is None for r in report['runs'])
    cloud.generate = lambda _: (_ for _ in ()).throw(RuntimeError('failed'))
    report = evaluate.benchmark(pipeline, [{'query': 'RSS', 'relevant_sources': []}], {'cloud': cloud}, 1)
    assert report['summary']['cloud']['success_rate'] == 0


def test_quality_review_requires_exact_answer():
    quality = load_day28('audit_quality')
    row = dict(question='RSS', provider='local', repeat=1, answer='Верный ответ', prompt_sha256='context')
    report = {'runs':[row], 'summary':{'local':{}}}
    review = dict(question='RSS', provider='local', repeat=1,
                  answer_sha256=quality.answer_hash(row), prompt_sha256='context', score=2, notes='Проверено по источнику')
    assert quality.audit(report, [review])['runs'][0]['manual_quality'] == 2
    row['answer'] = 'Другая генерация'
    with pytest.raises(ValueError, match='review'):
        quality.audit(report, [review])


def test_web_config_does_not_generate(pipeline):
    web = load_day28('server')
    model = FakeModel()
    pipeline.llm = model
    server = ThreadingHTTPServer(('127.0.0.1', 0), web.make_handler(pipeline))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urllib.request.urlopen(base + '/api/config') as response:
            assert json.load(response)['mode'] == 'local'
        assert not model.prompts
        request = urllib.request.Request(base + '/api/ask', data=b'{"question":"RSS"}',
                    headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request) as response:
            assert json.load(response)['has_citations']
        request.add_header('Origin', 'http://example.com')
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
