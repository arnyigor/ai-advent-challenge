"""Local comparison dashboard for the Day 21 indexes."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

from compare import DEFAULT_REPORT, compare_indexes
from embeddings import create_embedder
from index_store import chunks_for_source, index_stats, list_sources, search
from loaders import load_corpus
from day21_pipeline import DEFAULT_INDEX_DIR, DEFAULT_MODEL, build_indexes

DAY = Path(__file__).resolve().parent
WEB = DAY / "web"


def _safe_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def current_state() -> dict:
    _, corpus = load_corpus()
    indexes = {}
    for name in ("fixed", "structure"):
        path = DEFAULT_INDEX_DIR / f"{name}.sqlite3"
        indexes[name] = index_stats(path) if path.is_file() else None
    return {"corpus": corpus, "indexes": indexes, "comparison": _safe_json(DEFAULT_REPORT)}


def create_server(port: int = 0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.call_lock = threading.Lock()
    server.embedder = None
    server.embedder_model = None
    return server


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, *_args):
        pass

    def send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, maximum: int = 8192) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= maximum:
            raise ValueError("Некорректный размер запроса")
        value = json.loads(self.rfile.read(size))
        if not isinstance(value, dict):
            raise ValueError("Ожидается JSON-объект")
        return value

    def local_request(self) -> bool:
        expected = f"127.0.0.1:{self.server.server_port}"
        return self.headers.get("Host") == expected and self.headers.get("Origin") in (None, f"http://{expected}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json(current_state())
            return
        if parsed.path == "/api/sources":
            path = DEFAULT_INDEX_DIR / "structure.sqlite3"
            self.send_json({"sources": list_sources(path) if path.is_file() else []})
            return
        if parsed.path == "/api/document":
            source = parse_qs(parsed.query).get("source", [""])[0]
            documents, _ = load_corpus()
            document = next((item for item in documents if item.source == source), None)
            if document is None:
                self.send_json({"error": "Документ не найден"}, 404)
            else:
                self.send_json({
                    "source": document.source,
                    "title": document.title,
                    "language": document.language,
                    "chars": len(document.text),
                    "text": document.text,
                })
            return
        if parsed.path == "/api/chunks":
            source = parse_qs(parsed.query).get("source", [""])[0]
            if not source or len(source) > 300:
                self.send_json({"error": "Некорректный source"}, 400)
                return
            try:
                self.send_json({name: chunks_for_source(DEFAULT_INDEX_DIR / f"{name}.sqlite3", source) for name in ("fixed", "structure")})
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)
            return
        if parsed.path.startswith("/api/"):
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        super().do_GET()

    def do_POST(self):
        if not self.local_request():
            self.send_json({"error": "Только локальный интерфейс"}, 403)
            return
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/build", "/api/search"}:
            self.send_json({"error": "Маршрут не найден"}, 404)
            return
        if not self.server.call_lock.acquire(blocking=False):
            self.send_json({"error": "Операция уже выполняется"}, 409)
            return
        try:
            body = self.read_json()
            if parsed.path == "/api/build":
                model = body.get("model", DEFAULT_MODEL)
                if not isinstance(model, str) or not model.strip() or len(model) > 200:
                    raise ValueError("Некорректная embedding-модель")
                embedding = create_embedder(model.strip())
                built = build_indexes(model_name=model.strip(), embedder=embedding)
                compared = compare_indexes(model_name=model.strip(), embedder=embedding)
                self.server.embedder = embedding
                self.server.embedder_model = model.strip()
                self.send_json({"built": built, "comparison": compared})
                return
            query = body.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 500:
                raise ValueError("Введите запрос длиной 1–500 символов")
            fixed_stats = index_stats(DEFAULT_INDEX_DIR / "fixed.sqlite3")
            model = fixed_stats["embedding_model"]
            if self.server.embedder is None or self.server.embedder_model != model:
                self.server.embedder = create_embedder(model)
                self.server.embedder_model = model
            vector = self.server.embedder.encode_query(query.strip())
            self.send_json({
                "query": query.strip(),
                "model": model,
                "results": {name: search(DEFAULT_INDEX_DIR / f"{name}.sqlite3", vector) for name in ("fixed", "structure")},
            })
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)
        finally:
            self.server.call_lock.release()


if __name__ == "__main__":
    server = create_server(int(os.environ.get("DAY21_WEB_PORT", "0")))
    print(f"Day 21: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
