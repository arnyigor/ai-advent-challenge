"""Local comparison UI for Day 24 retrieval filtering."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse

from evaluate import DEFAULT_QUESTIONS, DEFAULT_REPORT, load_questions
from rag_agent import (
    DEFAULT_MODEL,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TOP_K_AFTER,
    DEFAULT_TOP_K_BEFORE,
    RagAgent,
)

DAY = Path(__file__).resolve().parent
WEB = DAY / "web"


def _read_report():
    return json.loads(DEFAULT_REPORT.read_text(encoding="utf-8")) if DEFAULT_REPORT.is_file() else None


def create_server(port: int = 0, *, agent=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.call_lock = threading.Lock()
    server.agent = agent
    return server


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, *_args):
        pass

    def send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def local_request(self) -> bool:
        expected = f"127.0.0.1:{self.server.server_port}"
        return self.headers.get("Host") == expected and self.headers.get("Origin") in (None, f"http://{expected}")

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/state":
            self.send_json(
                {
                    "questions": load_questions(DEFAULT_QUESTIONS),
                    "report": _read_report(),
                    "default_model": DEFAULT_MODEL,
                    "settings": {
                        "top_k_before": DEFAULT_TOP_K_BEFORE,
                        "top_k_after": DEFAULT_TOP_K_AFTER,
                        "similarity_threshold": DEFAULT_SIMILARITY_THRESHOLD,
                    },
                }
            )
            return
        if route.startswith("/api/"):
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/ask":
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        if not self.local_request():
            self.send_json({"error": "Только локальный интерфейс"}, 403)
            return
        if not self.server.call_lock.acquire(blocking=False):
            self.send_json({"error": "Сравнение уже выполняется"}, 409)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError("Некорректный размер запроса")
            body = json.loads(self.rfile.read(size))
            question = body.get("question") if isinstance(body, dict) else None
            if not isinstance(question, str) or not question.strip() or len(question) > 1000:
                raise ValueError("Введите вопрос длиной 1–1000 символов")
            if self.server.agent is None:
                self.server.agent = RagAgent()
            self.send_json(self.server.agent.compare(question))
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 502)
        finally:
            self.server.call_lock.release()


if __name__ == "__main__":
    server = create_server(int(os.environ.get("DAY24_WEB_PORT", "0")))
    print(f"Day 24: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
