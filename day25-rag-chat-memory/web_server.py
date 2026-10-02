"""Local chat UI for Day 25: RAG answers with sources plus task-state memory."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

from chat_agent import (
    DEFAULT_DATA_DIR,
    DEFAULT_HISTORY_TURNS,
    DEFAULT_INDEX,
    DEFAULT_MODEL,
    ChatAgent,
)

DAY = Path(__file__).resolve().parent
WEB = DAY / "web"


def create_server(port: int = 0, *, agent: ChatAgent | None = None, data_dir: Path = DEFAULT_DATA_DIR):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.chat_lock = threading.Lock()
    server.agent = agent
    server.data_dir = Path(data_dir)
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

    def _agent(self) -> ChatAgent:
        if self.server.agent is None:
            self.server.agent = ChatAgent(data_dir=self.server.data_dir)
        return self.server.agent

    def do_GET(self):
        route = urlparse(self.path).path
        if route == '/api/evaluation':
            report_path = DAY / 'results' / 'scenarios.json'
            if not report_path.exists():
                self.send_json({'error': 'Сначала запустите evaluate.py'}, 404)
                return
            report = json.loads(report_path.read_text(encoding='utf-8'))
            self.send_json({'created_at': report['created_at'], 'model': report['model'],
                            'summary': report['summary'], 'scenarios': [
                                {'id': s['id'], 'title': s['title'], 'summary': s['summary']}
                                for s in report['scenarios']]})
            return
        if route == "/api/state":
            agent = self._agent()
            self.send_json({
                "default_model": agent.model,
                "settings": {"history_turns": agent.history_turns},
                "sessions": agent.chats.sessions(),
            })
            return
        if route == "/api/session":
            if not self.local_request():
                self.send_json({"error": "Только локальный интерфейс"}, 403)
                return
            session_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            try:
                self.send_json(self._agent().session(session_id))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 404)
            return
        if route.startswith("/api/"):
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        if route not in ("/api/session", "/api/chat"):
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        if not self.local_request():
            self.send_json({"error": "Только локальный интерфейс"}, 403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({'error': 'Некорректный размер запроса'}, 400)
            return
        if not 0 <= size <= 8192:
            self.send_json({"error": "Некорректный размер запроса"}, 400)
            return
        try:
            body = json.loads(self.rfile.read(size)) if size else {}
            if not isinstance(body, dict):
                raise ValueError("Ожидался JSON-объект")
            agent = self._agent()
            if route == "/api/session":
                self.send_json(agent.session(agent.create_session()))
                return
            # Chat turns run the retrieval-generation-verification pipeline,
            # so concurrent requests are rejected instead of interleaved.
            if not self.server.chat_lock.acquire(blocking=False):
                self.send_json({"error": "Предыдущий ответ ещё обрабатывается"}, 409)
                return
            try:
                message = body.get("message")
                session_id = body.get("session_id")
                if not isinstance(session_id, str) or not session_id.strip():
                    raise ValueError("Передайте session_id из /api/session")
                self.send_json(agent.turn(session_id, message))
            finally:
                self.server.chat_lock.release()
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except FileNotFoundError as exc:
            self.send_json({"error": str(exc)}, 500)
        except Exception as exc:  # noqa: BLE001 - surface the failure to the UI
            self.send_json({"error": str(exc)}, 502)


if __name__ == "__main__":
    server = create_server(int(os.environ.get("DAY25_WEB_PORT", "0")))
    print(f"Day 25: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
