"""Локальный web-чат Day 6. UI вызывает агента, а не LLM напрямую."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DAY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DAY_DIR.parent
WEB_DIR = DAY_DIR / "web"
for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent import (
    AgentConfig,
    AgentCancelledError,
    AgentStore,
    AgentUnavailableError,
    ChatAgent,
    DefaultInputPolicy,
    DefaultOutputPolicy,
    GEMINI_THINKING_LEVELS,
)
from providers import create_default_providers, public_provider_status


def create_agent() -> ChatAgent:
    return ChatAgent(create_default_providers())


def public_agent_config() -> dict:
    """Возвращает только безопасные настройки Agent Box для интерфейса."""
    config = AgentConfig()
    return {
        "temperature": config.temperature,
        "max_output_tokens": config.max_output_tokens,
        "max_history_messages": config.max_history_messages,
        "max_input_chars": config.max_input_chars,
        "max_output_chars": config.max_output_chars,
        "thinking_level": config.thinking_level,
        "thinking_levels": list(GEMINI_THINKING_LEVELS),
        "input_policy": DefaultInputPolicy.__name__,
        "output_policy": DefaultOutputPolicy.__name__,
        "judge_enabled": False,
        "system_prompt_configured": bool(config.system_prompt),
    }


def create_server(host: str, port: int, store: AgentStore | None = None):
    server = ThreadingHTTPServer((host, port), Handler)
    server.agent_store = store or AgentStore(create_agent)
    return server


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, _format, *_args):
        pass

    def _json(self, payload: dict | list, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 65_536:
            raise ValueError("Слишком большой запрос")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Некорректный JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("JSON должен быть объектом")
        return payload

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self._json(
                {
                    "agent": "ChatAgent",
                    "providers": public_provider_status(),
                    "config": public_agent_config(),
                }
            )
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/chat", "/api/reset", "/api/cancel"}:
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            session_id = str(payload.get("session_id") or "default")
            store = self.server.agent_store
            if parsed.path == "/api/reset":
                store.reset(session_id)
                self._json({"ok": True})
                return
            if parsed.path == "/api/cancel":
                self._json({"ok": store.cancel(session_id)})
                return
            reply = store.get(session_id).ask(
                payload.get("message"),
                provider_id=payload.get("provider") or None,
                thinking_level=payload.get("thinking_level") or None,
            )
            self._json({"reply": reply.to_dict()})
        except (TypeError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except AgentCancelledError as exc:
            self._json({"error": str(exc), "cancelled": True}, HTTPStatus.CONFLICT)
        except AgentUnavailableError as exc:
            self._json(
                {"error": str(exc), "attempts": list(exc.attempts)},
                HTTPStatus.BAD_GATEWAY,
            )


def main():
    parser = argparse.ArgumentParser(description="Day 6 agent web chat")
    parser.add_argument("--host", default=os.environ.get("DAY06_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY06_WEB_PORT", "8006")))
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    host, port = server.server_address
    print(f"Day 6 agent: http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
