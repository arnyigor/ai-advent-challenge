import importlib.util
from pathlib import Path
import subprocess
import sys
import pytest

DAY = Path(__file__).resolve().parents[1]/'day32-ai-code-review'
sys.path.insert(0, str(DAY))
spec = importlib.util.spec_from_file_location('day32_demo', DAY/'demo.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
import review


def test_real_diff_and_both_rag_corpora(tmp_path):
    base, head = demo.fixture(tmp_path/'repo')
    result = review.collect(tmp_path/'repo', base, head)
    assert result['changed_paths'] == ['pricing.py']
    assert '-    return price * (1 - percent / 100)' in result['diff']
    assert '+    return price * (1 - percent)' in result['diff']
    assert {s['kind'] for s in result['sources']} == {'code', 'documentation'}
    assert any(s['path'] == 'checkout.py' for s in result['sources'])
    assert result['files'][0]['head'].startswith('1: def discount')


def test_secret_oversize_deleted_and_symlink(tmp_path):
    repo = tmp_path/'repo'
    base, _ = demo.fixture(repo)
    (repo/'.env').write_text('fake secret never send')
    (repo/'secret.py').write_text('fake secret never send')
    (repo/'large.py').write_text('x'*25000)
    # Create a symlink Git object without Windows symlink privileges.
    oid = subprocess.check_output(['git','-C',str(repo),'hash-object','-w','--stdin'],input=b'pricing.py').decode().strip()
    subprocess.run(['git','-C',str(repo),'rm','checkout.py'],check=True,capture_output=True)
    subprocess.run(['git','-C',str(repo),'add','.'],check=True)
    subprocess.run(['git','-C',str(repo),'update-index','--add','--cacheinfo',f'120000,{oid},link.py'],check=True)
    subprocess.run(['git','-C',str(repo),'commit','-m','edge cases'],check=True,capture_output=True)
    result = review.collect(repo, base, 'HEAD')
    assert {s['path'] for s in result['skipped']} >= {'.env','secret.py','large.py','link.py'}
    assert 'fake secret never send' not in str(result)
    assert any(f['path']=='checkout.py' and f['head'] is None for f in result['files'])


@pytest.mark.parametrize('ref', ['--help', 'HEAD;echo', 'HEAD$(whoami)'])
def test_revision_rejects_shell_and_option_input(tmp_path, ref):
    with pytest.raises(ValueError):
        review.revision(tmp_path, ref)


def test_budget_is_visible(tmp_path, monkeypatch):
    base, head = demo.fixture(tmp_path/'repo')
    monkeypatch.setattr(review, 'MAX_DIFF', 1)
    result = review.collect(tmp_path/'repo', base, head)
    assert not result['files']
    assert result['skipped'][0]['reason'] == 'size/binary/symlink/budget'


def test_no_model_in_retrieval_mode(tmp_path, monkeypatch):
    base, head = demo.fixture(tmp_path/'repo')
    def fail(_):
        raise AssertionError('model must not run')
    monkeypatch.setattr(review, 'generate', fail)
    review.run(tmp_path/'repo', base, head, tmp_path/'output', True)
    assert (tmp_path/'output/context.json').exists()
    assert not (tmp_path/'output/review.md').exists()


def test_live_progress_follows_actual_pipeline(tmp_path, monkeypatch):
    base, head = demo.fixture(tmp_path/'repo')
    events = []
    def generate(payload):
        assert [stage for stage, _ in events] == ['git', 'context', 'model']
        assert payload['diff'] == events[1][1]['diff']
        return {'text': 'Test review', 'model': 'test', 'finish_reason': 'STOP'}
    monkeypatch.setattr(review, 'generate', generate)
    review.run(tmp_path/'repo', base, head, tmp_path/'output', progress=lambda stage, data: events.append((stage, data)))
    assert [stage for stage, _ in events] == ['git', 'context', 'model', 'complete']
    assert events[-1][1]['review'] == (tmp_path/'output/review.md').read_text(encoding='utf-8')
