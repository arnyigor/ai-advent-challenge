"""Local dashboard for RSS collection, digest generation, and stored results."""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse

from digest import build_digest, latest_digest
from feed_store import collect, recent_articles, recent_runs, reset_state
from scheduler import run_schedule, schedule_status

DAY = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DAY / "web"), **kwargs)

    def log_message(self, *_args):
        pass

    def send_json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlparse(self.path).path == "/api/state":
            self.send_json({**latest_digest(), "articles": recent_articles(), "runs": recent_runs(), "schedule": schedule_status(), "schedule_active": self.server.schedule_active, "simulation": os.environ.get("DAY18_SIMULATE_PROVIDER_FAILURES") == "1"})
        elif urlparse(self.path).path.startswith("/api/"):
            self.send_json({"error": "Unknown route"}, 404)
        else:
            super().do_GET()

    def do_POST(self):
        action = urlparse(self.path).path
        if action not in ("/api/collect", "/api/digest", "/api/reset"):
            self.send_json({"error": "Unknown route"}, 404)
            return
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected or self.headers.get("Origin") not in (None, f"http://{expected}"):
            self.send_json({"error": "Local application only"}, 403)
            return
        if not self.server.job_lock.acquire(blocking=False):
            self.send_json({"error": "Job already running"}, 409)
            return
        try:
            result = collect() if action == "/api/collect" else build_digest() if action == "/api/digest" else reset_state()
            self.send_json(result)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 502)
        finally:
            self.server.job_lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--demo-schedule", action="store_true", help="Run periodic jobs in this local process")
    parser.add_argument("--collect-seconds", type=int, default=15)
    parser.add_argument("--digest-seconds", type=int, default=45)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.job_lock = threading.Lock()
    server.schedule_active = args.demo_schedule
    stop = threading.Event()
    if args.demo_schedule:
        thread = threading.Thread(target=run_schedule, kwargs={"collect_seconds": args.collect_seconds, "digest_seconds": args.digest_seconds, "stop": stop, "job_lock": server.job_lock}, daemon=True)
        thread.start()
    print(f"Day 18: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
