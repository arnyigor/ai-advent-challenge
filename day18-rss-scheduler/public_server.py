"""Read-only public dashboard for the scheduled RSS digest."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
from urllib.parse import urlsplit

from feed_store import DB_PATH


PUBLIC = Path(__file__).with_name("public")
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/demo.mp4": ("day18-vps-url-demo.mp4", "video/mp4"),
}


def next_timer(name):
    try:
        result = subprocess.run(
            ["systemctl", "show", f"day18-{name}.timer", "-p", "NextElapseUSecRealtime", "--value"],
            capture_output=True, text=True, timeout=2, check=True,
        )
        value = result.stdout.strip()
        if value and value != "n/a":
            return datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc).isoformat()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def public_state():
    db = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        count = db.execute("SELECT count(*) FROM articles").fetchone()[0]
        last_run = db.execute("SELECT ran_at, found, inserted, error FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        row = db.execute("SELECT created_at, provider, model, body, article_count FROM digests ORDER BY id DESC LIMIT 1").fetchone()
        articles = [dict(item) for item in db.execute("SELECT url, title, published, discovered_at FROM articles ORDER BY discovered_at DESC, published DESC LIMIT 12")]
        runs = [dict(item) for item in db.execute("SELECT ran_at, found, inserted, error FROM runs ORDER BY id DESC LIMIT 5")]
    finally:
        db.close()
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": {"articles": count, "last_run": dict(last_run) if last_run else None},
        "digest": dict(row) if row else None,
        "articles": articles,
        "runs": runs,
        "schedule": {
            "collect": next_timer("collect"),
            "digest": next_timer("digest"),
        },
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_bytes(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/state":
            data = json.dumps(public_state(), ensure_ascii=False).encode("utf-8")
            self.send_bytes(data, "application/json; charset=utf-8")
        elif path == "/digest.txt":
            digest = public_state()["digest"]
            if digest:
                self.send_bytes(digest["body"].encode("utf-8"), "text/plain; charset=utf-8")
            else:
                self.send_bytes("Сводки пока нет.\n".encode("utf-8"), "text/plain; charset=utf-8", 404)
        elif path in FILES:
            filename, content_type = FILES[path]
            self.send_bytes((PUBLIC / filename).read_bytes(), content_type)
        elif path == "/healthz":
            self.send_bytes(b"ok\n", "text/plain; charset=utf-8")
        else:
            self.send_bytes(b"Not found\n", "text/plain; charset=utf-8", 404)

    def do_POST(self):
        self.send_bytes(b"Read only\n", "text/plain; charset=utf-8", 405)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
