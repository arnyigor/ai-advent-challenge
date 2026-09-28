"""Load the reproducible mixed documentation/code corpus."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re

from models import Document

DAY = Path(__file__).resolve().parent
DEFAULT_MANIFEST = DAY / "corpus_manifest.json"
TEXT_SUFFIXES = {".md", ".txt", ".py"}


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def _markdown_title(text: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return match.group(1).strip() if match else fallback


def _python_title(text: str, fallback: str) -> str:
    try:
        docstring = ast.get_docstring(ast.parse(text), clean=True)
    except SyntaxError:
        docstring = None
    return docstring.splitlines()[0].strip() if docstring else fallback


def _pdf_to_markdown(path: Path) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF loading requires PyMuPDF; install requirements.txt") from exc
    pages = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, 1):
            pages.append(f"## Page {index}\n\n{page.get_text('text').strip()}")
    return "\n\n".join(pages)


def load_document(path: Path, repo_root: Path) -> Document:
    if path.suffix.lower() == ".pdf":
        text = _normalise(_pdf_to_markdown(path))
        language = "pdf-markdown"
        title = path.stem.replace("_", " ")
    else:
        text = _normalise(path.read_text(encoding="utf-8", errors="replace"))
        language = "python" if path.suffix.lower() == ".py" else "markdown"
        fallback = path.stem.replace("_", " ")
        title = _python_title(text, fallback) if language == "python" else _markdown_title(text, fallback)
    return Document(
        source=path.relative_to(repo_root).as_posix(),
        title=title,
        file=path.name,
        language=language,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def load_corpus(manifest_path: Path | str = DEFAULT_MANIFEST) -> tuple[list[Document], dict]:
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo_root = (manifest_path.parent / manifest.get("repo_root", "..")).resolve()
    paths: set[Path] = set()
    for item in manifest["sources"]:
        root = (repo_root / item["root"]).resolve()
        if not root.is_dir() or repo_root not in root.parents:
            raise ValueError(f"Invalid corpus root: {item['root']}")
        for pattern in item["include"]:
            for path in root.glob(pattern):
                if path.is_file() and (path.suffix.lower() in TEXT_SUFFIXES or path.suffix.lower() == ".pdf"):
                    paths.add(path.resolve())
    documents = [load_document(path, repo_root) for path in sorted(paths, key=lambda value: value.as_posix())]
    words = sum(len(re.findall(r"\S+", document.text)) for document in documents)
    chars = sum(len(document.text) for document in documents)
    stats = {
        "description": manifest.get("description", ""),
        "files": len(documents),
        "words": words,
        "chars": chars,
        "pages_at_500_words": round(words / 500, 1),
        "repo_root": str(repo_root),
    }
    return documents, stats
