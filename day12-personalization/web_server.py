"""Local demo API for user profiles and personalized requests."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from personalized_agent import LAYERS, MemoryStore, PersonalizedAgent
from profile_store import ProfileStore
from providers import LiveProvider
from model_providers import ReasonerProvider

DAY_DIR = Path(__file__).resolve().parent


class DemoProvider:
    """Deterministic offline demo; live providers remain available separately."""

    def generate(self, *, system: str, messages: list[dict[str, str]]):
        from agent import ProviderReply
        address = next((line.split(": ", 1)[1] for line in system.splitlines() if line.startswith("Обращение: ")), "")
        role = next((line.split("[РОЛЬ: ", 1)[1].split("]", 1)[0] for line in system.splitlines() if "[РОЛЬ: " in line), "")
        answer = f"{address}, " if address else ""
        answer += {"analyst": "требования: определить сценарий и критерии готовности.", "architect": "структура: интерфейс, профиль, агент.", "developer": "реализация: обработать запрос и сохранить результат.", "reviewer": "проверка: протестировать профиль и порядок ролей."}.get(role, "отвечаю с учётом вашего профиля.")
        return ProviderReply(answer, "demo", "deterministic")


def create_server(host="127.0.0.1", port=0, *, directory=None, provider=None):
    server = ThreadingHTTPServer((host, port), Handler)
    root = Path(directory or DAY_DIR / "data")
    server.memory_store = MemoryStore(root)
    server.profile_store = ProfileStore(root)
    server.agents = {"demo": PersonalizedAgent(server.memory_store, server.profile_store, provider or DemoProvider())}
    if provider is None:
        for name in ("auto", "deepseek", "gemini", "wormsoft"):
            server.agents[name] = PersonalizedAgent(server.memory_store, server.profile_store, LiveProvider(name))
        server.agents["reasoner"] = PersonalizedAgent(server.memory_store, server.profile_store, ReasonerProvider())
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

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 100_000:
            raise ValueError("Слишком большой запрос")
        value = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(value, dict):
            raise ValueError("JSON должен быть объектом")
        return value

    def do_GET(self):
        if urlparse(self.path).path == "/api/profile":
            try:
                user = parse_qs(urlparse(self.path).query).get("user_id", ["demo"])[0]
                self.send_json({"profile": self.server.profile_store.get(user)})
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        if route not in ("/api/profile", "/api/memory", "/api/preview", "/api/chat"):
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            data = self.body()
            user_id = data.get("user_id", "demo")
            if route == "/api/profile":
                self.send_json({"profile": self.server.profile_store.save(user_id, data.get("profile"))})
                return
            ids = {"user_id": user_id, "session_id": data.get("session_id", "session-1"), "task_id": data.get("task_id", "task-1")}
            if route == "/api/memory":
                self.server.memory_store.save_fact("working", **ids, key=data.get("key", ""), value=data.get("value", ""))
                self.send_json({"memory": self.server.memory_store.snapshot(**ids)})
                return
            include = data.get("include", list(LAYERS))
            if not isinstance(include, list) or any(not isinstance(x, str) for x in include):
                raise ValueError("include должен быть списком")
            agent = self.server.agents.get(data.get("provider_id", "demo"))
            if agent is None:
                raise ValueError("Неизвестный провайдер")
            kwargs = {**ids, "user_text": data.get("text", ""), "include": tuple(include)}
            if route == "/api/preview":
                self.send_json({"context": agent.build_request(**kwargs)})
            else:
                self.send_json(agent.ask(**kwargs))
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY12_WEB_PORT", "0")))
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"Day 12: http://{args.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
