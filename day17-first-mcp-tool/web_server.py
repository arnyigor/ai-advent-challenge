"""Local Day 17 app: send a request to the agent and show its real MCP call."""

import argparse
import asyncio
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse

from git_agent import QUESTIONS, ask


DAY_DIR = Path(__file__).resolve().parent


def create_server(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.call_lock = threading.Lock()
    return server


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DAY_DIR / "web"), **kwargs)

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
        if urlparse(self.path).path != "/api/ask":
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected or self.headers.get("Origin") not in (None, f"http://{expected}"):
            self.send_json({"error": "Запрос разрешён только из локального приложения"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Некорректный размер запроса")
            body = json.loads(self.rfile.read(length))
            scope = body.get("scope") if isinstance(body, dict) else None
            if scope not in QUESTIONS:
                raise ValueError("Выберите один из доступных запросов")
        except (ValueError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
            return
        if not self.server.call_lock.acquire(blocking=False):
            self.send_json({"error": "Агент уже выполняет запрос"}, 409)
            return
        try:
            self.send_json(asyncio.run(ask(scope)))
        except Exception as exc:
            self.send_json({"error": str(exc)}, 502)
        finally:
            self.server.call_lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY17_WEB_PORT", "0")))
    args = parser.parse_args()
    server = create_server(args.port)
    print(f"Day 17: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
