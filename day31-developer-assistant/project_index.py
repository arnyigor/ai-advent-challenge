"""Explicit project documentation corpus, using the Day 21 SQLite contract."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import sys

DAY = Path(__file__).resolve().parent
ROOT = DAY.parent
sys.path.insert(0, str(ROOT / 'day21-document-indexing'))
sys.path.insert(0, str(ROOT / 'day28-local-rag'))
from chunkers import chunk_documents
from loaders import load_document
from index_store import _corpus_hash, index_stats, write_index
from rag import OfflineEmbedder, Pipeline

DEFAULT_INDEX = DAY / 'data' / 'project.sqlite3'
EMBEDDING_MODEL = 'intfloat/multilingual-e5-small'


class StaleIndexError(ValueError):
    pass


def corpus(root=ROOT):
    root = Path(root).resolve()
    paths = [root / 'README.md']
    paths += sorted(root.glob('day[0-9][0-9]-*/README.md'))
    paths += sorted((root / 'docs').rglob('*.md'))
    safe = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or path.is_symlink():
            raise ValueError('Corpus path escapes repository or is a symlink')
        if any(part.startswith('.') for part in path.relative_to(root).parts):
            continue
        if not resolved.is_file() or resolved.stat().st_size > 256000:
            raise ValueError('Missing or oversized documentation file')
        safe.append(resolved)
    if not any(p.is_relative_to(root / 'docs') for p in safe):
        raise ValueError('Project requires a docs/ Markdown corpus')
    return [load_document(p, root) for p in sorted(set(safe), key=lambda p: p.as_posix())]


def build_index(index=DEFAULT_INDEX, root=ROOT, embedder=None):
    docs = corpus(root)
    chunks = chunk_documents(docs, strategy='structure', chunk_size=1000)
    embedder = embedder or OfflineEmbedder(EMBEDDING_MODEL)
    if embedder.name.startswith('hash'):
        raise ValueError('Production index requires semantic embeddings')
    # OfflineEmbedder exposes the actual loaded SentenceTransformer.
    vectors = embedder.model.encode(['passage: ' + c.text for c in chunks],
        normalize_embeddings=True, batch_size=16, show_progress_bar=False).tolist()
    return write_index(index, docs, chunks, vectors, embedding_model=embedder.name,
                       embedding_dim=embedder.dimension, chunk_size=1000)


def inspect_index(index=DEFAULT_INDEX):
    stats = index_stats(index)
    with closing(sqlite3.connect(Path(index).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        stats['sources'] = [row[0] for row in conn.execute('SELECT source FROM documents ORDER BY source')]
    return stats


class ProjectPipeline(Pipeline):
    def __init__(self, index=DEFAULT_INDEX, root=ROOT, **kwargs):
        self.root = Path(root).resolve()
        super().__init__(index=index, **kwargs)

    def assert_fresh(self):
        self.stats = index_stats(self.index)
        if _corpus_hash(corpus(self.root)) != self.stats['corpus_hash']:
            raise StaleIndexError('Документация изменилась. Выполните assistant.py --index.')

    def retrieve(self, question, vector):
        # Generic API/structure questions refer to the current assistant. Other
        # daily APIs should enter the prompt only when that day is named.
        days = set(re.findall(r'\b(?:day\s*0?(\d{1,2})|д(?:ень|ня|не)\s*0?(\d{1,2}))\b', question, re.I))
        prefixes = {f'day{int(a or b):02d}-' for a, b in days}
        count = self.top_k
        try:
            self.top_k = 64  # Parent collects 32 vector + 32 FTS candidates.
            rows = super().retrieve(question, vector)
        finally:
            self.top_k = count
        allowed = []
        for row in rows:
            source = row['source']
            current = source == 'README.md' or source.startswith(('docs/', 'day31-developer-assistant/'))
            named_day = any(source.startswith(prefix) for prefix in prefixes)
            if current or named_day:
                allowed.append(row)
        return allowed[:count]
