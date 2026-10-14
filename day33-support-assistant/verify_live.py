"""Two live LLM calls through the running HTTP application, save evidence."""
import asyncio
import json
import os
from pathlib import Path
import httpx
from verify_support import wait_ready


async def main():
    base = os.environ.get('DAY33_VERIFY_URL', 'http://127.0.0.1:8833')
    results = []
    async with httpx.AsyncClient(base_url=base, timeout=100) as client:
        await wait_ready(client)
        for ticket_id in ['SK-1042', 'SK-1043']:
            r = await client.post('/api/chat', json={'ticket_id': ticket_id,
                'message': 'Почему не работает авторизация?'})
            r.raise_for_status()
            data = r.json()
            assert data['mode'] == 'live_llm'
            assert data['mcp']['steps'] == ['initialize', 'tools/list', 'tools/call']
            assert any(p['source_ids'] for p in data['paragraphs'])
            joined = '\n'.join(p['text'] for p in data['paragraphs'])
            expected = 'LINK_EXPIRED' if ticket_id == 'SK-1042' else 'SESSION_MISMATCH'
            assert expected in joined, joined
            results.append(data)
            print(ticket_id, data['model'], data['elapsed_ms'], joined)
    out = Path(__file__).parent / 'evidence' / 'live-answers.json'
    out.write_text(json.dumps({'url': base, 'question': 'Почему не работает авторизация?',
        'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
