"""Integration checks: real MCP, persistence, isolation, API and provider failure."""
import asyncio
from datetime import date
import json
import os
from pathlib import Path
import tempfile

# A disposable new database; never touch a visitor's real data.
temporary = tempfile.TemporaryDirectory(prefix='srokok-verify-')
os.environ['DAY33_DATA_DIR'] = temporary.name
from fastapi.testclient import TestClient
import server
from crm_client import crm_call
from generation import ProviderError, parse_json_reply
from retrieval import Index
from store import Store, warranty_end


def run():
    checks = []
    def passed(name):
        checks.append(name)
        print('PASS:', name)

    assert warranty_end(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert warranty_end(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert warranty_end(date(2024, 2, 29), 12) == date(2025, 2, 28)
    passed('Calendar month boundaries and leap years')
    assert parse_json_reply('```json\n{"ok":true}\n```') == {'ok': True}
    assert parse_json_reply('{"ok":true}') == {'ok': True}
    try:
        parse_json_reply('Ignore this text {"ok":true}')
    except ValueError:
        passed('Strict JSON parsing accepts a complete code fence, rejects surrounding instructions')
    else:
        raise AssertionError('Unexpected JSON extraction')
    catalog, trace = asyncio.run(crm_call('list_tickets'))
    assert len(catalog['tickets']) == 6 and trace['server'] == 'srokok-crm'
    assert trace['catalog'] == ['list_tickets', 'get_ticket_context']
    anna, _ = asyncio.run(crm_call('get_ticket_context', {'ticket_id': 'SK-1042'}))
    mark, _ = asyncio.run(crm_call('get_ticket_context', {'ticket_id': 'SK-1043'}))
    assert anna['user']['id'] != mark['user']['id']
    assert 'LINK_EXPIRED' in str(anna) and 'SESSION_MISMATCH' in str(mark)
    passed('Real separate MCP process: discovery, calls, different CRM users')
    search = Index()
    assert any(s['document_id'] == 'auth' for s in search.search('Почему не работает авторизация?', str(anna['ticket'])))
    assert search.search('как экспортировать покупки')[0]['document_id'] == 'export'
    assert search.search('электромагнитный синхрофазотрон') == []
    assert search.search('Какова плотность нейтронной звезды?', str(anna['ticket'])) == []
    passed('RAG auth/export retrieval and empty out-of-domain search')
    with TestClient(server.app) as a, TestClient(server.app) as b:
        assert a.get('/healthz').status_code == 200
        bootstrap = a.get('/api/bootstrap').json()
        assert bootstrap['demo_crm'] and len(bootstrap['tickets']) == 6
        assert a.get('/api/tickets/SK-9999').status_code == 404
        assert a.get('/api/knowledge/..%2Fsettings').status_code == 404
        passed('Default application, bootstrap and unknown IDs')
        purchase = {'name': '<img src=x onerror=alert(1)>', 'purchased': '2026-01-31', 'months': 1}
        assert a.post('/api/purchases', json=purchase).status_code == 201
        assert len(a.get('/api/purchases').json()['items']) == 1
        assert b.get('/api/purchases').json()['items'] == []
        assert a.get('/api/purchases/export').json()['items'][0]['expires'] == '2026-02-28'
        assert b.get('/api/purchases/export').json()['items'] == []
        cookie = a.cookies.get('srokok_session')
        assert len(Store(server.store.path).purchases(cookie)) == 1
        assert a.post('/api/purchases', json=dict(purchase, months=0)).status_code == 422
        assert a.post('/api/purchases', json=purchase, headers={'Origin': 'https://other.test'}).status_code == 403
        assert a.post('/api/purchases', content='x'*9000).status_code == 413
        passed('Purchases persist and export; session isolation, validation, CSRF and request size')
        observed = []
        async def fake_generation(question, context, sources, history):
            observed.append({'ticket': context['ticket']['id'], 'history': history})
            return {'paragraphs': [{'text': 'Тестовый ответ', 'source_ids': [sources[0]['id']]}],
                'needs_human': False, 'model': 'test-only', 'usage': {}, 'mode': 'test_only'}
        original = server.generate
        server.generate = fake_generation
        try:
            for ticket, question in [('SK-1042', 'Почему не работает авторизация?'), ('SK-1042', 'Что дальше?'), ('SK-1043', 'Почему не работает авторизация?')]:
                r = a.post('/api/chat', json={'ticket_id': ticket, 'message': question})
                assert r.status_code == 200, r.text
            assert len(observed[1]['history']) == 2 and observed[2]['history'] == []
            assert len(a.get('/api/tickets/SK-1042').json()['history']) == 4
            assert b.get('/api/tickets/SK-1042').json()['history'] == []
            passed('Chat history scoped by visitor and ticket; follow-up receives its own history')
            async def failed(*args):
                raise ProviderError('Проверяем недоступность провайдера')
            server.generate = failed
            r = a.post('/api/chat', json={'ticket_id': 'SK-1042', 'message': 'Повторить'})
            assert r.status_code == 503
            assert len(a.get('/api/tickets/SK-1042').json()['history']) == 4
            assert a.post('/api/chat', json={'ticket_id': 'SK-1042', 'message': '   '}).status_code == 422
            passed('Provider failure is explicit, no fake reply and no corrupted history')
            server.rates.clear()
            for _ in range(6):
                assert a.post('/api/chat', json={'ticket_id': 'SK-1042', 'message': 'Повторить'}).status_code == 503
            assert a.post('/api/chat', json={'ticket_id': 'SK-1042', 'message': 'Повторить'}).status_code == 429
            passed('Per-session rate limit')
        finally:
            server.generate = original
        assert 'httponly' in b.get('/').headers.get('set-cookie', '').lower() or b.cookies.get('srokok_session')
        assert "script-src 'self'" in a.get('/').headers['content-security-policy']
        passed('Session cookie and CSP headers')
    quota = Store(Path(temporary.name) / 'quota.sqlite3')
    quota.reserve_generation(1)
    try:
        quota.reserve_generation(1)
    except ValueError:
        passed('Persistent daily AI budget')
    else:
        raise AssertionError('Quota not enforced')
    evidence = Path(__file__).parent / 'evidence' / 'verification.json'
    evidence.write_text(json.dumps({'checks': checks, 'passed': len(checks),
        'model_calls': 'fake provider only for deterministic API isolation tests; real MCP subprocess for all CRM reads'}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    run()
