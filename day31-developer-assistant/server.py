"""Loopback developer assistant UI; one shared service for HTTP and CLI."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading

from assistant import Assistant
from project_index import StaleIndexError, inspect_index
from model_provider import settings

DAY = Path(__file__).resolve().parent


def make_handler(assistant):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, value, mime='application/json; charset=utf-8'):
            raw = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, dict) else value
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self):
            host = f'127.0.0.1:{self.server.server_port}'
            return self.headers.get('Host') == host and self.headers.get('Origin', 'http://' + host) == 'http://' + host

        def do_GET(self):
            if not self.allowed():
                return self.send(403, {'error': 'Forbidden host/origin'})
            if self.path == '/api/config':
                provider, model = settings()
                return self.send(200, {'index': inspect_index(assistant.pipeline.index),
                    'provider': provider, 'model': model})
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                     '/style.css': ('style.css', 'text/css')}
            if self.path not in files:
                return self.send(404, {'error': 'Not found'})
            name, mime = files[self.path]
            self.send(200, (DAY / 'web' / name).read_bytes(), mime + '; charset=utf-8')

        def do_POST(self):
            if not self.allowed():
                return self.send(403, {'error': 'Forbidden host/origin'})
            if self.path != '/api/help':
                return self.send(404, {'error': 'Not found'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8192:
                    return self.send(413, {'error': 'Body size limit'})
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise ValueError('Expected JSON object')
                if not lock.acquire(blocking=False):
                    return self.send(409, {'error': 'Предыдущий запрос ещё выполняется'})
                try:
                    result = assistant.help(value.get('command'))
                    result.pop('prompt', None)
                    return self.send(200, result)
                finally:
                    lock.release()
            except StaleIndexError as exc:
                self.send(409, {'error': str(exc)})
            except (ValueError, TypeError) as exc:
                self.send(400, {'error': str(exc)})
            except Exception as exc:
                self.send(502, {'error': 'Ошибка MCP/RAG/модели: ' + type(exc).__name__ +
                          '. Проверьте выбранный API, кеш embeddings и Git.'})

        def log_message(self, *args):
            pass

    return Handler


if __name__ == '__main__':
    port = int(os.environ.get('DAY31_WEB_PORT', '8796'))
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(Assistant()))
    print(f'http://127.0.0.1:{server.server_port} — /help, документация + MCP', flush=True)
    server.serve_forever()
