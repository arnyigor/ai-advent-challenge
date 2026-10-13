"""Explicit provider selection, free-model guard, cloud response and errors."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'day31-developer-assistant'))
import model_provider as providers


def test_unknown_provider(monkeypatch):
    monkeypatch.setenv('DAY31_LLM_PROVIDER','invalid')
    with pytest.raises(ValueError): providers.settings()


def test_openrouter_paid_model_rejected():
    with pytest.raises(ValueError,match=':free'):
        providers.CloudModel('openrouter','paid-model','system')


def test_openrouter_missing_key(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False)
    with pytest.raises(ValueError,match='not set'):
        providers.CloudModel('openrouter','openrouter/free','system').generate('question')


def test_cloud_prompt_and_result(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','fixture-token')
    class Response:
        status_code=200
        def json(self):
            return {'model':'free-model','choices':[{'message':{'content':'answer [1]'},'finish_reason':'stop'}],'usage':{'cost':0}}
    def post(url,**kwargs):
        assert kwargs['json']['messages']==[{'role':'system','content':'instructions'},{'role':'user','content':'docs + live branch'}]
        assert kwargs['allow_redirects'] is False
        return Response()
    monkeypatch.setattr(providers.requests,'post',post)
    result=providers.CloudModel('openrouter','openrouter/free','instructions').generate('docs + live branch')
    assert result['answer']=='answer [1]' and result['usage']['cost']==0


def test_api_error_does_not_expose_response_or_fallback(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','fixture-token')
    class Response:
        status_code=429
        text='private-provider-details'
    monkeypatch.setattr(providers.requests,'post',lambda *a,**k:Response())
    with pytest.raises(RuntimeError,match='HTTP 429; no paid fallback') as error:
        providers.CloudModel('openrouter','openrouter/free','system').generate('question')
    assert 'private-provider-details' not in str(error.value)
