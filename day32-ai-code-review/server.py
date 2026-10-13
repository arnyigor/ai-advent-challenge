"""Loopback live pipeline viewer. Runs the same reviewer as GitHub Actions."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from review import run

DAY = Path(__file__).resolve().parent


def make_handler(repo, base, head, output):
    lock = threading.Lock()
    state = {'stage': 'ready', 'events': [], 'context': None, 'result': None, 'review': None}

    def progress(stage, data):
        with lock:
            state['stage'] = stage
            state['events'].append({'stage': stage, 'time': time.strftime('%H:%M:%S'),
                'message': {'git': 'Git: читаем diff и файлы PR', 'context': 'RAG: найдены документация и код',
                            'model': 'Gemini: отправлен diff, файлы и RAG', 'complete': 'Ревью сохранено в review.md'}[stage]})
            if stage == 'context':
                state['context'] = data
            if stage == 'complete':
                state.update(data)

    def worker():
        try:
            run(repo, base, head, output, progress=progress)
        except Exception:
            with lock:
                state['stage'] = 'error'
                state['events'].append({'time': time.strftime('%H:%M:%S'), 'message': 'Ошибка пайплайна; проверьте модель и конфигурацию.'})

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, data, mime='application/json; charset=utf-8'):
            raw = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self):
            host = f'127.0.0.1:{self.server.server_port}'
            return self.headers.get('Host') == host and self.headers.get('Origin', 'http://'+host) == 'http://'+host

        def do_GET(self):
            if not self.allowed():
                return self.send(403, {'error': 'Forbidden host/origin'})
            if self.path == '/api/state':
                with lock:
                    return self.send(200, {**state, 'base': base, 'head': head})
            files = {'/': ('index.html','text/html'), '/app.js': ('app.js','text/javascript'), '/style.css': ('style.css','text/css')}
            if self.path not in files:
                return self.send(404, {'error': 'Not found'})
            name, mime = files[self.path]
            self.send(200, (DAY/'web'/name).read_bytes(), mime+'; charset=utf-8')

        def do_POST(self):
            if not self.allowed():
                return self.send(403, {'error': 'Forbidden host/origin'})
            if self.path != '/api/run':
                return self.send(404, {'error': 'Not found'})
            with lock:
                if state['stage'] not in {'ready', 'complete', 'error'}:
                    return self.send(409, {'error': 'Already running'})
                state.update(stage='starting', events=[], context=None, result=None, review=None)
            threading.Thread(target=worker, daemon=True).start()
            self.send(202, {'started': True})

        def log_message(self, *args):
            pass

    return Handler


if __name__ == '__main__':
    spec = json.loads((DAY/'evidence/demo.json').read_text(encoding='utf-8'))
    server = ThreadingHTTPServer(('127.0.0.1', int(os.environ.get('DAY32_WEB_PORT', '8797'))),
        make_handler(DAY/'evidence/demo-repo', spec['base'], spec['head'], DAY/'evidence'))
    print(f'http://127.0.0.1:{server.server_port}', flush=True)
    server.serve_forever()
