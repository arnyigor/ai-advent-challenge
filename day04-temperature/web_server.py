"""Local web server for the Day 4 Temperature cockpit."""
from __future__ import annotations
import argparse
import json
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
from tools.llm.gemini import MODEL_CHAIN
from tools.llm.deepseek import DEFAULT_MODEL as DEEPSEEK_DEFAULT_MODEL
from tools.llm.registry import has_key_for, missing_key_message

RUNS = {}

class QueueReporter:
    def __init__(self, events):
        self.events = events
    def emit(self, kind, payload):
        self.events.put({"type": kind, "data": payload})

class RunSession:
    def __init__(self):
        self.events = queue.Queue()
        self.thread = None
        self.started_at = time.time()
        self.finished = False
        self.cancel_event = threading.Event()

def _run_experiment(run_id, payload):
    session = RUNS[run_id]
    reporter = QueueReporter(session.events)
    try:
        model = payload.get("model") or None
        if model:
            model_chain = [model]
        else:
            # Day 4 — лаборатория температуры на DeepSeek: deepseek приоритетен,
            # gemini-цепочка — только fallback, если ключа DeepSeek нет.
            model_chain = [f"deepseek:{DEEPSEEK_DEFAULT_MODEL}"] + list(MODEL_CHAIN)

        # Фильтруем только недоступные (без ключа) модели, но НЕ режем цепочку:
        # runner выполняет fallback при отказе провайдера во время эксперимента.
        available = [m for m in model_chain if has_key_for(m)]
        if not available:
            raise RuntimeError(missing_key_message(model_chain[0]))
        model_chain = available

        repeats = int(payload.get("repeats", 3))
        concurrency = int(payload.get("concurrency", 3))

        def on_event(kind, data):
            reporter.emit(kind, data)

        doc = run_experiment(model_chain, repeats, concurrency, on_event=on_event)

        out_path = RESULTS_DIR / f"run-{int(time.time())}-{run_id[:8]}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)

        reporter.emit("ExperimentFinished", {"document": doc, "file": "results/" + out_path.name})
    except Exception as exc:
        reporter.emit("ExperimentFailed", {"error": str(exc)})
    finally:
        session.finished = True
        reporter.emit("StreamClosed", {})

class TemperatureLabHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/results":
            items = []
            if RESULTS_DIR.exists():
                for path in sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            doc = json.load(f)
                        items.append({
                            "id": "results/" + path.name,
                            "name": path.name,
                            "model": doc.get("model_spec"),
                            "modified": int(path.stat().st_mtime),
                        })
                    except Exception:
                        pass
            self._json_response(items)
            return

        if parsed.path == "/api/result":
            query = parse_qs(parsed.query)
            file_id = query.get("id", [""])[0]
            if file_id.startswith("results/"):
                path = (RESULTS_DIR / file_id.removeprefix("results/")).resolve()
                if RESULTS_DIR.resolve() in path.parents or path == RESULTS_DIR.resolve():
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            self._json_response(json.load(f))
                            return
                    except Exception:
                        pass
            self._json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/events"):
            run_id = parsed.path.split("/")[3]
            self._stream_events(run_id)
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/cancel"):
            run_id = parsed.path.split("/")[3]
            session = RUNS.get(run_id)
            if not session:
                self._json_response({"error": "Run not found"}, HTTPStatus.NOT_FOUND)
                return
            session.cancel_event.set()
            self._json_response({"ok": True, "run_id": run_id})
            return

        if parsed.path == "/api/run":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
            except ValueError:
                self._json_response({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
                return

            run_id = uuid.uuid4().hex
            session = RunSession()
            RUNS[run_id] = session
            session.thread = threading.Thread(target=_run_experiment, args=(run_id, payload), daemon=True)
            session.thread.start()
            self._json_response({"run_id": run_id}, HTTPStatus.ACCEPTED)
            return

        self._json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def _json_response(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self, run_id):
        session = RUNS.get(run_id)
        if not session:
            self.send_error(HTTPStatus.NOT_FOUND, "Run not found")
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
                event = {"type": "Heartbeat", "data": {"server_time": time.time()}}
            body = json.dumps(event, ensure_ascii=False)
            try:
                self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break
            if event["type"] == "StreamClosed":
                break

def main():
    parser = argparse.ArgumentParser(description="Day 4 Temperature web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), TemperatureLabHandler)
    print(f"Day 4 Temperature Lab running at http://{args.host}:{args.port}/")
    server.serve_forever()

if __name__ == "__main__":
    main()