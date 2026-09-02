"""Local web server for the Day 3 Reasoning Lab cockpit."""

from __future__ import annotations

import argparse
import dataclasses
import json
import queue
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

DAY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DAY_DIR.parent
WEB_DIR = DAY_DIR / "web"
RESULTS_DIR = DAY_DIR / "results"

for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from day3_reasoning_modes import (  # noqa: E402
    RunCancelled,
    aggregate,
    build_json_document,
    estimate_calls,
    failure_counts,
    run_with_fallback,
    split_model_spec,
    verdict,
    write_json_document,
)
from methods import make_generation_config  # noqa: E402
from tasks import TASKS, verify_gold  # noqa: E402
from tools.llm.gemini import MODEL_CHAIN, has_gemini_api_key  # noqa: E402
from tools.llm.deepseek import has_deepseek_api_key  # noqa: E402
#: Четыре способа фиксированы заданием — браузер не может их сузить.
CHALLENGE_METHODS = ["direct", "cot", "self_prompt", "panel"]


RUNS: dict[str, "RunSession"] = {}
MODEL_OPTIONS = [
    {
        "provider": "Gemini",
        "id": "gemini:gemini-3.5-flash-lite",
        "model": "gemini-3.5-flash-lite",
        "availableForDay3": True,
        "source": "day01 llm-demo fallback chain",
    },
    {
        "provider": "Gemini",
        "id": "gemini:gemini-3.5-flash",
        "model": "gemini-3.5-flash",
        "availableForDay3": True,
        "source": "day01 llm-demo fallback chain",
    },
    {
        "provider": "Gemini",
        "id": "gemini:gemini-3.6-flash",
        "model": "gemini-3.6-flash",
        "availableForDay3": True,
        "source": "day01 llm-demo fallback chain",
    },
    {
        "provider": "Gemini",
        "id": "gemini:gemini-3.7-flash",
        "model": "gemini-3.7-flash",
        "availableForDay3": True,
        "source": "day03 current fallback chain",
    },
    {
        "provider": "Gemini",
        "id": "gemini:gemini-2.5-flash",
        "model": "gemini-2.5-flash",
        "availableForDay3": True,
        "source": "day01/day1_llm.py",
    },
    {
        "provider": "llama.cpp",
        "model": "qwen-27b",
        "availableForDay3": False,
        "source": "day01 llm-demo backend",
    },
    {
        "provider": "Ollama",
        "model": "llama3.2",
        "availableForDay3": False,
        "source": "day01 llm-demo backend",
    },
    {
        "provider": "DeepSeek",
        "id": "deepseek:deepseek-v4-flash",
        "model": "deepseek-v4-flash",
        "availableForDay3": True,
        "source": "DeepSeek OpenAI-compatible chat/completions",
        "requiresKey": "DEEPSEEK_API_KEY",
    },
    {
        "provider": "OpenAI",
        "model": "gpt-4o-mini",
        "availableForDay3": False,
        "source": "day01 llm-demo backend",
    },
    {
        "provider": "RouterAI",
        "model": "qwen/qwen3.8-27b",
        "availableForDay3": False,
        "source": "day01 llm-demo backend",
    },
    {
        "provider": "Mock",
        "model": "echo-1",
        "availableForDay3": False,
        "source": "day01 llm-demo fallback",
    },
]


class QueueReporter:
    def __init__(self, events: queue.Queue) -> None:
        self.events = events
        self.completed_methods = 0

    def emit(self, event: object) -> None:
        if event.__class__.__name__ == "MethodFinished":
            self.completed_methods += 1
        self.events.put(_event_payload(event))


class RunSession:
    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.started_at = time.time()
        self.finished = False
        self.cancel_event = threading.Event()
        self.cancelled = False


def _cleanup_old_runs(max_history: int = 50) -> None:
    """Ограничивает размер кэша: удаляет самые старые завершённые сессии."""
    if len(RUNS) <= max_history:
        return
    sorted_keys = sorted(RUNS.keys(), key=lambda k: RUNS[k].started_at)
    for k in sorted_keys[: len(RUNS) - max_history]:
        if RUNS[k].finished:
            del RUNS[k]


def _json_response(handler: SimpleHTTPRequestHandler, payload, status=HTTPStatus.OK):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _event_payload(event: object) -> dict:
    name = event.__class__.__name__
    if dataclasses.is_dataclass(event):
        data = dataclasses.asdict(event)
    else:
        data = {}
    return {"type": name, "data": data}


def _task_payload(task) -> dict:
    return {
        "id": task.id,
        "family": task.family,
        "prompt": task.prompt,
        "baseline": task.baseline(),
    }


def _selected_task(payload: dict):
    task_id = str(payload.get("task_id") or "").strip()
    return next((t for t in TASKS if t.id == task_id), None)


def _has_key_for_model(model_spec: str | None) -> bool:
    provider, _model = split_model_spec(model_spec)
    if provider == "deepseek":
        return has_deepseek_api_key()
    return has_gemini_api_key()


def _missing_key_message(model_spec: str | None) -> str:
    provider, _model = split_model_spec(model_spec)
    if provider == "deepseek":
        return "DEEPSEEK_API_KEY is not set"
    return "GEMINI_API_KEY is not set"


def _list_result_files() -> list[dict]:
    items = []
    for base, prefix in ((RESULTS_DIR, "results/"), (ROOT_DIR, "root/")):
        if not base.exists():
            continue
        pattern = "*.json" if base == RESULTS_DIR else "day3*.json"
        for path in sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = json.load(f)
            except (OSError, ValueError):
                continue
            items.append(
                {
                    "id": prefix + path.name,
                    "name": path.name,
                    "model": doc.get("model_used"),
                    "thinking": doc.get("thinking_level"),
                    "repeats": doc.get("repeats"),
                    "runs": len(doc.get("runs") or []),
                    "error": doc.get("error"),
                    "modified": int(path.stat().st_mtime),
                }
            )
    return items


def _resolve_result(result_id: str) -> Path:
    result_id = unquote(result_id)
    if result_id.startswith("results/"):
        path = (RESULTS_DIR / result_id.removeprefix("results/")).resolve()
        root = RESULTS_DIR.resolve()
    elif result_id.startswith("root/"):
        path = (ROOT_DIR / result_id.removeprefix("root/")).resolve()
        root = ROOT_DIR.resolve()
    else:
        raise ValueError("Unknown result location")
    if root not in path.parents and path != root:
        raise ValueError("Result path escapes its directory")
    if path.suffix != ".json" or not path.exists():
        raise ValueError("Result file not found")
    return path


def _run_experiment(run_id: str, payload: dict) -> None:
    session = RUNS[run_id]
    reporter = QueueReporter(session.events)
    try:
        verify_gold()

        # Одна выбранная задача, один прогон, четыре фиксированных способа.
        task_id = str(payload.get("task_id") or "").strip()
        task = _selected_task(payload)
        if task is None:
            raise ValueError(f"Unknown task_id: {task_id!r}")
        selected_tasks = [task]

        methods = CHALLENGE_METHODS
        repeats = 1
        thinking = payload.get("thinking") or "low"
        # Web challenge mode делает всего 5 последовательных вызовов; скрытый
        # pacer создавал искусственные паузы между запросами.
        rpm = 0.0
        model = payload.get("model") or None
        if not _has_key_for_model(model):
            raise RuntimeError(_missing_key_message(model))
        model_chain = [model] if model else MODEL_CHAIN
        gcfg = make_generation_config(thinking)

        results, model_used, attempts = run_with_fallback(
            repeats,
            methods,
            selected_tasks,
            model_chain,
            gcfg,
            rpm,
            quiet=True,
            reporter=reporter,
            cancel_event=session.cancel_event,
            stream=True,
        )
        agg = aggregate(results, methods, selected_tasks)
        failures = failure_counts(results)
        final_verdict = verdict(agg, methods)
        out_path = RESULTS_DIR / f"run-{int(time.time())}-{run_id[:8]}.json"
        doc = build_json_document(
            repeats,
            thinking,
            rpm,
            methods,
            selected_tasks,
            model_chain,
            agg,
            failures,
            model_used,
            results=results,
            attempts=attempts,
            v=final_verdict,
        )
        write_json_document(out_path, doc)
        session.events.put(
            {
                "type": "RunSaved",
                "data": {"file": "results/" + out_path.name, "document": doc},
            }
        )
    except RunCancelled:
        session.cancelled = True
        session.events.put(
            {
                "type": "ExperimentCancelled",
                "data": {"completed_methods": reporter.completed_methods},
            }
        )
    except Exception as exc:
        session.events.put({"type": "RunError", "data": {"message": str(exc)}})
    finally:
        session.finished = True
        session.events.put({"type": "StreamClosed", "data": {}})


class ReasoningLabHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/tasks":
            _json_response(
                self,
                [
                    {
                        "id": t.id,
                        "family": t.family,
                        "prompt": t.prompt,
                        "baseline": t.baseline(),
                    }
                    for t in TASKS
                ],
            )
            return
        if parsed.path == "/api/results":
            _json_response(self, _list_result_files())
            return
        if parsed.path == "/api/models":
            _json_response(self, MODEL_OPTIONS)
            return
        if parsed.path == "/api/result":
            query = parse_qs(parsed.query)
            try:
                path = _resolve_result(query.get("id", [""])[0])
                with open(path, "r", encoding="utf-8") as f:
                    _json_response(self, json.load(f))
            except (OSError, ValueError) as exc:
                _json_response(self, {"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/events"):
            run_id = parsed.path.split("/")[3]
            self._stream_events(run_id)
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/cancel"):
            run_id = parsed.path.split("/")[3]
            session = RUNS.get(run_id)
            if not session:
                _json_response(self, {"error": "Run not found"}, HTTPStatus.NOT_FOUND)
                return
            session.cancel_event.set()
            session.cancelled = True
            _json_response(
                self,
                {"ok": True, "run_id": run_id, "state": "cancelling"},
            )
            return
        if parsed.path != "/api/run":
            _json_response(self, {"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except ValueError:
            _json_response(self, {"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        task = _selected_task(payload)
        task_id = str(payload.get("task_id") or "").strip()
        if task is None:
            _json_response(
                self,
                {"error": f"Unknown task_id: {task_id!r}"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        _cleanup_old_runs()
        run_id = uuid.uuid4().hex
        session = RunSession()
        RUNS[run_id] = session
        session.thread = threading.Thread(
            target=_run_experiment, args=(run_id, payload), daemon=True
        )
        session.thread.start()
        # Одна задача, один прогон, четыре способа: 1+1+2+1 = 5 вызовов.
        _json_response(
            self,
            {
                "run_id": run_id,
                "task": _task_payload(task),
                "calls_estimate": estimate_calls(1, CHALLENGE_METHODS, [task]),
            },
            HTTPStatus.ACCEPTED,
        )

    def _stream_events(self, run_id: str) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 3 Reasoning Lab web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ReasoningLabHandler)
    print(f"Reasoning Lab running at http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
