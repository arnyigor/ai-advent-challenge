"""Check model decisions, real MCP routing and storage guard."""
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import ValidationError
import pytest

DAY = Path(__file__).resolve().parents[1] / "day20-mcp-orchestration"
sys.path.insert(0, str(DAY))
from orchestrator import Router, run
from gemini_agent import GeminiAgent


class ScriptedModel:
    """Deterministic Gemini-shaped responses; each next action observes prior tool data."""
    def __init__(self):
        self.calls = []

    def __call__(self, request):
        catalog = {item['name'] for item in request['tools'][0]['functionDeclarations']}
        assert catalog == {'knowledge.search', 'knowledge.read', 'analysis.summarize', 'analysis.verify', 'storage.save', 'storage.read'}
        history = request['contents']
        self.calls.append(history)
        query = history[0]['parts'][0]['text']
        observations = [part['functionResponse'] for message in history if message['role'] == 'user' for part in message['parts'] if 'functionResponse' in part]
        result = {entry['name']: entry['response'] for entry in observations}
        if not observations:
            action = ('knowledge.search', {'query': query.replace('без сохранения', '').strip()})
        elif not result['knowledge.search']['ids']:
            action = None
        else:
            items = [entry['response'] for entry in observations if entry['name'] == 'knowledge.read']
            unread = [id for id in result['knowledge.search']['ids'] if id not in [item['id'] for item in items]]
            if unread:
                action = ('knowledge.read', {'id': unread[0]})
            elif 'analysis.summarize' not in result:
                action = ('analysis.summarize', {'items': items})
            elif 'analysis.verify' not in result:
                action = ('analysis.verify', {'items': items, **result['analysis.summarize']})
            elif 'без сохранения' in query or not result['analysis.verify']['valid']:
                action = None
            elif 'storage.save' not in result:
                action = ('storage.save', {'content': result['analysis.summarize']['summary']})
            elif 'storage.read' not in result:
                action = ('storage.read', {'id': result['storage.save']['id']})
            else:
                action = None
        part = {'functionCall': {'name': action[0], 'args': action[1], 'id': str(len(self.calls))}} if action else {'text': 'Готово.'}
        return {'candidates': [{'content': {'role': 'model', 'parts': [part]}}]}


def model():
    return GeminiAgent(transport=ScriptedModel())


def test_long_flow(tmp_path, monkeypatch):
    monkeypatch.setenv('DAY20_OUTPUT_DIR', str(tmp_path))
    result = asyncio.run(run(agent=model()))
    trace = result['trace']
    assert [step['tool'] for step in trace] == ['knowledge.search', *['knowledge.read'] * 3, 'analysis.summarize', 'analysis.verify', 'storage.save', 'storage.read']
    assert {step['server'] for step in trace} == {'knowledge', 'analysis', 'storage'}
    assert trace[4]['arguments']['items'] == [step['result'] for step in trace[1:4]]
    assert trace[6]['arguments']['content'] == trace[4]['result']['summary']
    assert trace[7]['arguments']['id'] == trace[6]['result']['id']
    assert result['verified'] and result['model_turns'] == 9
    assert Path(result['file']).read_text(encoding='utf-8') == result['content']


@pytest.mark.parametrize('query,count', [('MCP без сохранения',6), ('RSS',6), ('несуществующийзапрос',1)])
def test_branches(query, count, tmp_path, monkeypatch):
    monkeypatch.setenv('DAY20_OUTPUT_DIR', str(tmp_path))
    result = asyncio.run(run(query, agent=model()))
    assert len(result['trace']) == count
    if query != 'RSS':
        assert result['file'] is None
        assert not list(tmp_path.iterdir())


def test_model_history_retains_call_and_result():
    def fake(request):
        return {'candidates': [{'content': {'role': 'model', 'parts': [{'functionCall': {'name': 'knowledge.search', 'args': {'query': 'MCP'}, 'id': 'call-1'}}]}}]}
    client = GeminiAgent(transport=fake)
    client.history = [{'role': 'user', 'parts': [{'text': 'MCP'}]}]
    choice = asyncio.run(client.next([{'name': 'knowledge.search', 'description': 'search', 'inputSchema': {'type': 'object'}}]))
    client.observe(choice, {'ids': ['d16']})
    assert client.history[1]['parts'][0]['functionCall']['name'] == 'knowledge.search'
    assert client.history[2]['parts'][0]['functionResponse']['response']['ids'] == ['d16']


def test_unknown_route():
    with pytest.raises(ValueError, match='Неизвестный маршрут'):
        asyncio.run(Router().call('read', {}, 'ambiguous'))


def test_step_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('DAY20_OUTPUT_DIR', str(tmp_path))
    with pytest.raises(Exception):
        asyncio.run(run(agent=model(), max_steps=1))
    assert not list(tmp_path.iterdir())


def test_real_router_guards_and_errors(tmp_path, monkeypatch):
    monkeypatch.setenv('DAY20_OUTPUT_DIR', str(tmp_path))
    async def scenario():
        router = Router()
        async with AsyncExitStack() as stack:
            await router.connect(stack, json.loads((DAY / 'servers.json').read_text()))
            with pytest.raises(ValidationError):
                await router.call('knowledge.read', {'id': 123}, 'bad schema')
            with pytest.raises(RuntimeError, match='Сохранение разрешено'):
                await router.call('storage.save', {'content': 'unverified'}, 'model bypass')
            assert not router.trace
            with pytest.raises(RuntimeError, match='Error executing tool read'):
                await router.call('storage.read', {'id': '../outside'}, 'bad id')
    asyncio.run(scenario())
    assert not list(tmp_path.iterdir())
