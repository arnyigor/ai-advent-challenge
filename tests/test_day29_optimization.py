import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('day29_benchmark', Path(__file__).resolve().parents[1] / 'day29-local-llm-optimization/benchmark.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_payload_and_empty_reason_preserved():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            return json.dumps({'choices': [{'message': {'content': ''}, 'finish_reason': 'length'}], 'usage': {'completion_tokens': 2048}}).encode()
    class Opener:
        def open(self, request, timeout):
            payload = json.loads(request.data)
            assert payload['max_tokens'] == 2048
            assert payload['temperature'] == 0
            assert 'context_window' not in payload
            assert payload['messages'][1]['content'] == 'frozen'
            return Response()
    client = module.LocalModel('http://127.0.0.1:8083/v1', 'fake')
    client.opener = Opener()
    result = module.generate(client, {'prompt': 'frozen'}, 'candidate')
    assert not result['ok']
    assert result['finish_reason'] == 'length'
    assert result['usage']['completion_tokens'] == 2048


def test_run_keeps_context_rotates_and_checkpoints(monkeypatch):
    monkeypatch.setattr(module, 'gpu_snapshot', lambda: None)
    calls = []
    def fake(client, prepared, profile):
        calls.append((prepared['prompt'], profile))
        if profile == 'baseline':
            raise TimeoutError()
        return dict(ok=True, answer='ok', finish_reason='stop')
    monkeypatch.setattr(module, 'generate', fake)
    frozen = [{'id': 1, 'prepared': {'prompt': 'same', 'question': 'q'}, 'prompt_sha256': module.digest('same')}]
    saved = []
    report = module.run(frozen, ['baseline', 'prompt'], 2, None, lambda r: saved.append(len(r['runs'])), {})
    assert calls == [('same', 'baseline'), ('same', 'prompt'), ('same', 'prompt'), ('same', 'baseline')]
    assert saved == [1, 2, 3, 4]
    assert report['summary']['baseline']['nonempty'] == 0
    assert report['runs'][0]['error'] == 'TimeoutError'
    frozen[0]['prepared']['prompt'] = 'tampered'
    with pytest.raises(ValueError, match='hash'):
        module.run(frozen, ['prompt'], 1, None, lambda r: None, {})


def test_report_escapes_model_output(tmp_path):
    report_spec = importlib.util.spec_from_file_location('day29_report', Path(module.DAY) / 'render_report.py')
    renderer = importlib.util.module_from_spec(report_spec)
    report_spec.loader.exec_module(renderer)
    path = tmp_path / 'run.json'
    path.write_text(json.dumps({'metadata': {}, 'summary': {}, 'runs': [dict(
        profile='baseline', case_id=1, repeat=1, question='q', answer='<script>alert(1)</script>')]}), encoding='utf-8')
    html = renderer.render([path])
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_quality_review_rejects_changed_answer(monkeypatch):
    review_spec = importlib.util.spec_from_file_location('day29_review', Path(module.DAY) / 'review_quality.py')
    reviewer = importlib.util.module_from_spec(review_spec)
    import sys
    monkeypatch.setitem(sys.modules, 'benchmark', module)
    review_spec.loader.exec_module(reviewer)
    report = {'runs': [dict(profile='baseline', repeat=1, case_id=1, answer='changed', prompt_sha256='context')]}
    reviews = [dict(profile='baseline', repeat=1, case_id=1, answer_sha256=module.digest('original'),
        prompt_sha256='context', score=2, notes='review')]
    with pytest.raises(ValueError, match='hashes'):
        reviewer.apply(report, reviews)


def test_selected_prompt_is_pinned_and_used(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'benchmark', module)
    ask_spec = importlib.util.spec_from_file_location('day29_ask', Path(module.DAY) / 'ask.py')
    ask = importlib.util.module_from_spec(ask_spec)
    ask_spec.loader.exec_module(ask)
    config = dict(profile='selected', system='pinned instructions', system_sha256=module.digest('pinned instructions'),
        temperature=0.1, max_tokens=4096, url='http://127.0.0.1:8081/v1', model='fake')
    path = tmp_path / 'selected.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    loaded = ask.load_config(path)
    monkeypatch.setenv('LOCAL_LLM_URL', 'http://127.0.0.1:8083/v1')
    monkeypatch.setenv('LOCAL_LLM_MODEL', 'unrelated-strata-model')
    selected_client = ask.ConfiguredModel(loaded).client
    assert selected_client.url == config['url']
    assert selected_client.model == config['model']
    def fake_generate(client, prepared, profile, received):
        assert prepared == {'prompt': 'context'}
        assert received == config
        return dict(ok=True, answer='answer')
    monkeypatch.setattr(ask, 'generate', fake_generate)
    assert ask.ConfiguredModel(loaded, client=object()).generate('context')['answer'] == 'answer'
    config['system'] = 'changed without revalidation'
    path.write_text(json.dumps(config), encoding='utf-8')
    with pytest.raises(ValueError, match='hash'):
        ask.load_config(path)
