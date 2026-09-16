"""Local Day 13 API and static web server."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from model_comparison import ModelComparator
from task_agent import TaskAgent
from task_state import TaskStateMachine, TaskStateStore

DAY_DIR = Path(__file__).resolve().parent


def create_server(host="127.0.0.1", port=0, *, directory=None):
    server = ThreadingHTTPServer((host, port), Handler)
    store = TaskStateStore(Path(directory or DAY_DIR / "data"))
    server.agent = TaskAgent(TaskStateMachine(store))
    server.comparator = ModelComparator()
    return server


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DAY_DIR / "web"), **kwargs)

    def log_message(self, *_args):
        pass

    def send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 100_000:
            raise ValueError("Слишком большой запрос")
        value = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(value, dict):
            raise ValueError("JSON должен быть объектом")
        return value

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/task":
            try:
                task_id = parse_qs(parsed.query).get("task_id", [""])[0]
                self.send_json(self.server.agent.status(task_id))
            except (ValueError, KeyError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            data = self.read_body()
            task_id = data.get("task_id", "")
            if route == "/api/task":
                response = self.server.agent.start(task_id, data.get("objective", ""))
            elif route == "/api/action":
                response = self.server.agent.act(task_id, data.get("action", ""), data.get("result", ""))
            elif route == "/api/pause":
                response = self.server.agent.pause(task_id, data.get("reason", ""))
            elif route == "/api/resume":
                response = self.server.agent.resume(task_id)
            elif route == "/api/compare":
                state = self.server.agent.machine.store.get(task_id)
                response = self.server.comparator.compare(state)
            else:
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json(response)
        except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY13_WEB_PORT", "0")))
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"Day 13: http://{args.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
