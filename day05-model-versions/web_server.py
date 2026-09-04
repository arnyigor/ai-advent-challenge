"""Local SSE web dashboard for Day 5."""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DAY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DAY_DIR.parent
WEB_DIR = DAY_DIR / "web"
RESULTS_DIR = DAY_DIR / "results"
for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from experiment import run_experiment
from tools.llm.registry import has_key_for

RUNS = {}


class RunSession:
    def __init__(self):
        self.events = queue.Queue()
        self.finished = False
        self.cancel_event = threading.Event()


def _run(run_id, payload):
    session = RUNS[run_id]

    def emit(kind, data):
        session.events.put({"type": kind, "data": data})

    try:
        doc = run_experiment(
            repeats=max(1, min(int(payload.get("repeats", 3)), 5)),
            local_url=payload.get("local_url") or None,
            ollama_url=payload.get("ollama_url") or None,
            local_cpu_url=payload.get("local_cpu_url") or None,
            include_local=bool(payload.get("include_local", True)),
            include_local_small=bool(payload.get("include_local_small", True)),
            include_local_cpu=bool(payload.get("include_local_cpu", True)),
            include_hf=bool(payload.get("include_hf", True)),
            include_api=bool(payload.get("include_api", True)),
            on_event=emit,
            cancel_event=session.cancel_event,
        )
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"run-{int(time.time())}-{run_id[:8]}.json"
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        emit("ExperimentFinished", {"document": doc, "file": f"results/{out.name}"})
    except Exception as exc:
        emit("ExperimentFailed", {"error": str(exc)})
    finally:
        session.finished = True
        emit("StreamClosed", {})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, _format, *_args):
        pass

    def _json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self._json({
                "local_available": bool(os.environ.get("LOCAL_LLM_URL")),
                "local_small_available": bool(os.environ.get("OLLAMA_URL")),
                "local_cpu_available": bool(os.environ.get("LOCAL_CPU_LLM_URL")),
                "gemini_available": has_key_for("gemini:gemini-3.6-flash"),
                "deepseek_available": has_key_for("deepseek:deepseek-v4-flash"),
            })
            return
        if parsed.path == "/api/results":
            items = []
            if RESULTS_DIR.exists():
                for path in sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                    try:
                        doc = json.loads(path.read_text(encoding="utf-8"))
                        items.append({"id": f"results/{path.name}", "name": path.name, "verdict": doc.get("verdict")})
                    except Exception:
                        continue
            self._json(items)
            return
        if parsed.path == "/api/result":
            file_id = parse_qs(parsed.query).get("id", [""])[0]
            if file_id.startswith("results/"):
                path = (RESULTS_DIR / file_id.removeprefix("results/")).resolve()
                if RESULTS_DIR.resolve() in path.parents and path.is_file():
                    self._json(json.loads(path.read_text(encoding="utf-8")))
                    return
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/events"):
            self._events(parsed.path.split("/")[3])
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except ValueError:
                self._json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
                return
            run_id = uuid.uuid4().hex
            RUNS[run_id] = RunSession()
            threading.Thread(target=_run, args=(run_id, payload), daemon=True).start()
            self._json({"run_id": run_id}, HTTPStatus.ACCEPTED)
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/cancel"):
            run_id = parsed.path.split("/")[3]
            session = RUNS.get(run_id)
            if not session:
                self._json({"error": "Run not found"}, HTTPStatus.NOT_FOUND)
                return
            session.cancel_event.set()
            self._json({"ok": True})
            return
        self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def _events(self, run_id):
        session = RUNS.get(run_id)
        if not session:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        while True:
            try:
                event = session.events.get(timeout=2)
            except queue.Empty:
                event = {"type": "Heartbeat", "data": {}}
            try:
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break
            if event["type"] == "StreamClosed":
                break


def main():
    parser = argparse.ArgumentParser(description="Day 5 model comparison dashboard")
    parser.add_argument("--host", default=os.environ.get("DAY05_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAY05_WEB_PORT", "0")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    host, port = server.server_address
    print(f"Day 5 dashboard: http://{host}:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
