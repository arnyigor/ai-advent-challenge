"""Local API and static demo for Day 15."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lifecycle_assistant import LifecycleAssistant
from model_comparison import ModelComparator
from task_lifecycle import LifecycleContract
from task_store import TaskStore

DAY_DIR = Path(__file__).resolve().parent


def create_server(host="127.0.0.1", port=0, *, data_dir=None, contract_path=None):
    server = ThreadingHTTPServer((host, port), Handler)
    server.contract = LifecycleContract.load(contract_path or DAY_DIR / "lifecycle.json")
    server.store = TaskStore(data_dir or DAY_DIR / "data")
    server.assistant = LifecycleAssistant(server.contract, server.store)
    server.comparator = ModelComparator(server.contract)
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
        if length < 0 or length > 150_000:
            raise ValueError("Слишком большой запрос")
        value = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(value, dict):
            raise ValueError("JSON должен быть объектом")
        return value

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/lifecycle":
            self.send_json(self.server.contract.public_dict())
            return
        if parsed.path == "/api/task":
            try:
                task_id = parse_qs(parsed.query).get("task_id", [""])[0]
                self.send_json(self.server.assistant.status(task_id))
            except (ValueError, KeyError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            body = self.read_body()
            task_id = body.get("task_id", "")
            if route == "/api/task":
                result = self.server.assistant.start(task_id, body.get("objective", ""))
            elif route == "/api/transition":
                version = body.get("expected_version")
                if version is not None and not isinstance(version, int):
                    raise ValueError("expected_version должен быть целым числом")
                result = self.server.assistant.transition(task_id, body.get("action", ""),
                                                          body.get("result", ""), version)
            elif route == "/api/pause":
                result = self.server.assistant.pause(task_id, body.get("reason", ""))
            elif route == "/api/resume":
                result = self.server.assistant.resume(task_id)
            elif route == "/api/compare":
                state = self.server.store.get(task_id)
                result = self.server.comparator.compare(state, body.get("request", ""))
            else:
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json(result)
        except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY15_WEB_PORT", "0")))
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"Day 15: http://{args.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
