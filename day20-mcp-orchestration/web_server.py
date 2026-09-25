"""Local web view of the real Day 20 MCP pipeline."""

import asyncio
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse

from orchestrator import run

DAY = Path(__file__).resolve().parent


def create_server(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.call_lock = threading.Lock()
    return server


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DAY / "web"), **kwargs)

    def log_message(self, *_args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path.startswith("/api/"):
            self.send_json({"error": "Маршрут не найден"}, 404)
        else:
            super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected or self.headers.get("Origin") not in (None, f"http://{expected}"):
            self.send_json({"error": "Только локальный интерфейс"}, 403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1024:
                raise ValueError("Некорректный размер запроса")
            body = json.loads(self.rfile.read(size))
            query = body.get("query") if isinstance(body, dict) else None
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                raise ValueError("Введите запрос длиной 1–200 символов")
        except (ValueError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
            return
        if not self.server.call_lock.acquire(blocking=False):
            self.send_json({"error": "Цепочка уже выполняется"}, 409)
            return
        try:
            self.send_json(asyncio.run(run(query)))
        except Exception as exc:
            self.send_json({"error": str(exc)}, 502)
        finally:
            self.server.call_lock.release()


if __name__ == "__main__":
    server = create_server(int(os.environ.get("DAY20_WEB_PORT", "0")))
    print(f"Day 20: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
