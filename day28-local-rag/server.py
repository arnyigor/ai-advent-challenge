"""Loopback UI. Startup reads SQLite metadata, never contacts or loads a model."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
from rag import DAY, Pipeline


def make_handler(pipeline):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, content_type='application/json; charset=utf-8'):
            raw = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, dict) else body
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self):
            authority = f'127.0.0.1:{self.server.server_port}'
            return (self.headers.get('Host') == authority and
                    self.headers.get('Origin', 'http://' + authority) == 'http://' + authority)

        def do_GET(self):
            if not self.allowed():
                return self.send(403, {'error': 'Forbidden host/origin'})
            if self.path == '/api/config':
                return self.send(200, {'index': pipeline.stats, 'mode': 'local',
                             'model': os.environ.get('LOCAL_LLM_MODEL', 'не настроена')})
            if self.path == '/report':
                report = DAY / 'results/report.html'
                return self.send(200, report.read_bytes(), 'text/html; charset=utf-8') if report.is_file() else self.send(404, {'error': 'Отчёт ещё не подготовлен'})
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                     '/style.css': ('style.css', 'text/css')}
            if self.path not in files:
                return self.send(404, {'error': 'Not found'})
            name, mime = files[self.path]
            self.send(200, (DAY / 'web' / name).read_bytes(), mime + '; charset=utf-8')

        def do_POST(self):
            if not self.allowed():
                return self.send(403, {'error': 'Forbidden host/origin'})
            if self.path not in ('/api/ask', '/api/retrieve'):
                return self.send(404, {'error': 'Not found'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8192:
                    return self.send(413, {'error': 'Body size limit'})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected JSON object')
                question = data.get('question')
                if not lock.acquire(blocking=False):
                    return self.send(409, {'error': 'Предыдущий запрос ещё выполняется'})
                try:
                    result = pipeline.prepare(question)
                    if self.path == '/api/ask':
                        result = pipeline.answer(result)
                    return self.send(200, result)
                finally:
                    lock.release()
            except (ValueError, TypeError) as exc:
                self.send(400, {'error': str(exc)})
            except Exception as exc:
                # Avoid returning provider data or credentials to browser/logs.
                self.send(502, {'error': 'Ошибка локального пайплайна: ' + type(exc).__name__ +
                          '. Проверьте кеш embeddings и настройки локального API.'})

        def log_message(self, *args):
            pass

    return Handler


if __name__ == '__main__':
    port = int(os.environ.get('DAY28_WEB_PORT', '8793'))
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(Pipeline()))
    print(f'http://127.0.0.1:{port} — модели при старте не вызываются', flush=True)
    server.serve_forever()
