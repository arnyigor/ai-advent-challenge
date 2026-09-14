"""Local browser demo for the three Day 11 memory layers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DAY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DAY_DIR.parent
WEB_DIR = DAY_DIR / "web"
for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent import MemoryAgent
from memory_store import LAYERS, MemoryStore
from providers import LiveProvider


def create_server(host: str = "127.0.0.1", port: int = 0, *, directory: Path | None = None, provider=None):
    server = ThreadingHTTPServer((host, port), Handler)
    server.memory_store = MemoryStore(directory or DAY_DIR / "data")
    server.agents = {
        name: MemoryAgent(server.memory_store, provider or LiveProvider(name))
        for name in ("auto", "deepseek", "gemini", "wormsoft")
    }
    return server


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, _format, *_args):
        pass

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 100_000:
            raise ValueError("Слишком большой запрос")
        data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("JSON должен быть объектом")
        return data

    @staticmethod
    def _ids(data: dict) -> dict[str, str]:
        return {
            "user_id": str(data.get("user_id", "demo")),
            "session_id": str(data.get("session_id", "session-1")),
            "task_id": str(data.get("task_id", "task-1")),
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            args = parse_qs(parsed.query)
            ids = self._ids({k: v[0] for k, v in args.items() if v})
            try:
                self._json({"ids": ids, "memory": self.server.memory_store.snapshot(**ids)})
            except ValueError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        if route not in {"/api/memory", "/api/chat", "/api/preview"}:
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            data = self._body()
            ids = self._ids(data)
            if route == "/api/memory":
                self.server.memory_store.save_fact(
                    str(data.get("layer", "")), **ids,
                    key=str(data.get("key", "")), value=str(data.get("value", "")),
                )
                self._json({"memory": self.server.memory_store.snapshot(**ids)})
                return
            raw_include = data.get("include", list(LAYERS))
            if not isinstance(raw_include, list) or any(not isinstance(x, str) for x in raw_include):
                raise ValueError("include должен быть списком слоёв")
            include = tuple(raw_include)
            text = str(data.get("text", ""))
            if route == "/api/preview":
                self._json({"context": self.server.agents["auto"].build_request(**ids, user_text=text, include=include)})
                return
            provider_id = str(data.get("provider_id", "auto"))
            if provider_id not in self.server.agents:
                raise ValueError("Неизвестный провайдер")
            result = self.server.agents[provider_id].ask(**ids, user_text=text, include=include)
            self._json({**result, "memory": self.server.memory_store.snapshot(**ids)})
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY11_WEB_PORT", "0")))
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"Day 11: http://{args.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
