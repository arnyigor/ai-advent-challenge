"""Explicit deployment acceptance check: one service restart, same HTTP session."""
from argparse import ArgumentParser
import json
from pathlib import Path
import re
import subprocess
import time
import httpx


def main():
    parser = ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--key', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_.@-]+', args.target):
        raise ValueError('Invalid SSH target')
    ssh = ['ssh', '-o', 'BatchMode=yes', '-i', str(args.key), args.target]
    with httpx.Client(base_url=args.url, timeout=100) as client:
        client.get('/').raise_for_status()
        purchase = {'name': 'Проверка сохранения после перезапуска', 'purchased': '2026-01-31', 'months': 1}
        client.post('/api/purchases', json=purchase).raise_for_status()
        client.post('/api/chat', json={'ticket_id': 'SK-1045', 'message': 'Почему гарантия заканчивается 28 февраля?'}).raise_for_status()
        subprocess.run(ssh + ['sudo -n systemctl restart day33-support.service'], check=True)
        for _ in range(20):
            try:
                if client.get('/healthz').status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Service did not recover after restart')
        items = client.get('/api/purchases').json()['items']
        history = client.get('/api/tickets/SK-1045').json()['history']
        assert len(items) == 1 and items[0]['expires'] == '2026-02-28'
        assert len(history) == 2 and history[1]['content']['mode'] == 'live_llm'
        export = client.get('/api/purchases/export').json()
        assert len(export['items']) == 1
        with httpx.Client(base_url=args.url) as other:
            assert other.get('/api/purchases').json()['items'] == []
        video = client.get('/demo.mp4', headers={'Range': 'bytes=0-1023'})
        assert video.status_code == 206 and len(video.content) == 1024
        redirect = httpx.get(args.url.replace('https:', 'http:'), follow_redirects=False)
        assert redirect.status_code in {301, 308}
    service = subprocess.check_output(ssh + ['systemctl is-active day33-support.service caddy day18-public.service; systemctl is-enabled day33-support.service caddy; systemctl show day33-support.service --property=MemoryCurrent'], text=True)
    assert service.splitlines()[:5] == ['active', 'active', 'active', 'enabled', 'enabled']
    day18 = httpx.get('http://' + args.target.split('@')[-1] + ':8080/', timeout=20)
    assert day18.status_code == 200
    checks = {'https_validated': True, 'http_redirect': True, 'service_restart': True,
        'purchase_persisted': True, 'chat_persisted': True, 'export_isolated': True,
        'video_range_playback': True, 'day18_healthy': True, 'services': service}
    (Path(__file__).parent / 'evidence/deployment.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
