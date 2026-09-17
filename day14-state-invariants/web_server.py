"""Local API and static demo for Day 14."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from invariant_assistant import InvariantAssistant
from invariant_store import InvariantStore
from routerai_client import RouterAIClient

DAY_DIR = Path(__file__).resolve().parent


def create_server(host="127.0.0.1", port=0, *, invariant_path=None):
    server = ThreadingHTTPServer((host, port), Handler)
    store = InvariantStore(Path(invariant_path or DAY_DIR / "invariants.json"))
    model_client = RouterAIClient()
    server.invariant_store = store
    server.model_client = model_client
    server.assistant = InvariantAssistant(store, model_client)
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

    def do_GET(self):
        if urlparse(self.path).path == "/api/invariants":
            version, items = self.server.invariant_store.load()
            self.send_json({"version": version, "invariants": [item.public_dict() for item in items], "models": [
                {"id": "deterministic", "label": "Invariant Engine", "available": True},
                {"id": "routerai", "label": "Qwen3.8-27B · RouterAI", "available": self.server.model_client.available},
            ]})
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/ask":
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 100_000:
                raise ValueError("Слишком большой запрос")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("JSON должен быть объектом")
            self.send_json(self.server.assistant.answer(str(payload.get("request", "")), payload.get("history"), use_model=payload.get("model") == "routerai"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY14_WEB_PORT", "0")))
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"Day 14: http://{args.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
