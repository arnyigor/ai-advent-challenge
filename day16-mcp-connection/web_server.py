"""Day 16 local UI, following the HTTP server pattern from Day 15."""

import argparse
import asyncio
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse

from mcp_client import discover, error_message

DAY_DIR = Path(__file__).resolve().parent


def server_profiles():
    root = Path(os.environ.get("JARVIS_MCP_ROOT", DAY_DIR.parents[1] / "MCPs" / "McpServer"))
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    script = root / "server.py"
    return {
        "jarvis": {
            "id": "jarvis", "name": "Jarvis", "description": "Ваш MCP: файлы, поиск, код и документы",
            "available": python.is_file() and script.is_file(),
            "command": [str(python), str(script)],
        },
        "demo": {
            "id": "demo", "name": "Учебный сервер", "description": "Два простых инструмента: сложение и приветствие",
            "available": True, "command": None,
        },
    }


def create_server(port=0, *, profiles=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.profiles = profiles if profiles is not None else server_profiles()
    server.discovery_lock = threading.Lock()
    return server


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DAY_DIR / "web"), **kwargs)

    def log_message(self, *_args):
        pass

    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/servers":
            profiles = [{k: v for k, v in item.items() if k != "command"}
                        for item in self.server.profiles.values()]
            self.send_json({"servers": profiles})
        elif route.startswith("/api/"):
            self.send_json({"error": "Маршрут не найден"}, 404)
        else:
            super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/discover":
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        # Local UI may select a configured profile, never send an arbitrary command.
        origin = self.headers.get("Origin")
        expected = f"http://127.0.0.1:{self.server.server_port}"
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Некорректный размер запроса")
            body = json.loads(self.rfile.read(length))
            if self.headers.get("Host") != expected.removeprefix("http://") or (origin and origin != expected):
                self.send_json({"error": "Запрос разрешён только из локального интерфейса"}, 403)
                return
            if not isinstance(body, dict) or not isinstance(body.get("server_id"), str):
                raise ValueError("Нужно выбрать MCP-сервер")
            profile = self.server.profiles.get(body["server_id"])
            if not profile or not profile["available"]:
                raise ValueError("Сервер недоступен. Выберите учебный сервер или настройте JARVIS_MCP_ROOT")
        except (ValueError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
            return
        if not self.server.discovery_lock.acquire(blocking=False):
            self.send_json({"error": "Подключение уже выполняется. Дождитесь результата"}, 409)
            return
        events = []

        def on_event(stage, message):
            events.append({"stage": stage, "message": message,
                           "time": datetime.now().strftime("%H:%M:%S")})

        try:
            result = asyncio.run(discover(command=profile["command"], timeout=60, on_event=on_event))
            self.send_json({**result, "events": events, "profile": profile["id"]})
        except Exception as exc:
            on_event("error", "Не удалось получить каталог инструментов")
            self.send_json({"error": error_message(exc), "events": events}, 502)
        finally:
            self.server.discovery_lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY16_WEB_PORT", "0")))
    args = parser.parse_args()
    server = create_server(args.port)
    print(f"Day 16: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
