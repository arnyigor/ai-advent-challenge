"""Fixed-size and structure-aware chunking strategies."""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from models import Chunk, Document


@dataclass(frozen=True)
class Section:
    name: str
    start: int
    end: int


def _stable_id(strategy: str, document: Document, section: str, start: int, text: str) -> str:
    key = f"{strategy}\0{document.source}\0{section}\0{start}\0{hashlib.sha256(text.encode()).hexdigest()}"
    return f"{strategy}:{hashlib.sha256(key.encode()).hexdigest()[:20]}"


def _markdown_sections(text: str) -> list[Section]:
    matches = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    if not matches:
        return [Section("document", 0, len(text))]
    result: list[Section] = []
    if matches[0].start() > 0:
        result.append(Section("preamble", 0, matches[0].start()))
    stack: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        level, title = len(match.group(1)), match.group(2).strip()
        stack = [(old_level, old_title) for old_level, old_title in stack if old_level < level]
        stack.append((level, title))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result.append(Section(" > ".join(item[1] for item in stack), match.start(), end))
    return [section for section in result if text[section.start:section.end].strip()]


def _python_sections(text: str) -> list[Section]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [Section("module", 0, len(text))]
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
    if not nodes:
        return [Section("module", 0, len(text))]
    sections: list[Section] = []
    first = offsets[nodes[0].lineno - 1]
    if text[:first].strip():
        sections.append(Section("module", 0, first))
    for index, node in enumerate(nodes):
        start = offsets[node.lineno - 1]
        end = offsets[nodes[index + 1].lineno - 1] if index + 1 < len(nodes) else len(text)
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        sections.append(Section(f"{kind} {node.name}", start, end))
    return [section for section in sections if text[section.start:section.end].strip()]


def sections_for(document: Document) -> list[Section]:
    return _python_sections(document.text) if document.language == "python" else _markdown_sections(document.text)


def _section_at(sections: list[Section], position: int) -> str:
    for section in sections:
        if section.start <= position < section.end:
            return section.name
    return sections[-1].name if sections else "document"


def _make_chunk(document: Document, strategy: str, index: int, start: int, end: int, section: str) -> Chunk:
    text = document.text[start:end].strip()
    return Chunk(
        chunk_id=_stable_id(strategy, document, section, start, text),
        source=document.source,
        title=document.title,
        file=document.file,
        section=section,
        strategy=strategy,
        chunk_index=index,
        start_char=start,
        end_char=end,
        text=text,
        content_hash=document.content_hash,
        language=document.language,
    )


def fixed_chunks(document: Document, chunk_size: int = 1200, overlap: int = 200) -> list[Chunk]:
    if chunk_size < 200 or not 0 <= overlap < chunk_size:
        raise ValueError("chunk_size must be >= 200 and overlap must be smaller")
    sections = sections_for(document)
    chunks: list[Chunk] = []
    cursor = 0
    while cursor < len(document.text):
        end = min(len(document.text), cursor + chunk_size)
        if document.text[cursor:end].strip():
            chunks.append(_make_chunk(document, "fixed", len(chunks), cursor, end, _section_at(sections, cursor)))
        if end == len(document.text):
            break
        cursor = end - overlap
    return chunks


def _split_structural_section(document: Document, section: Section, chunk_size: int, overlap: int) -> list[tuple[int, int]]:
    if section.end - section.start <= chunk_size:
        return [(section.start, section.end)]
    ranges: list[tuple[int, int]] = []
    cursor = section.start
    while cursor < section.end:
        limit = min(section.end, cursor + chunk_size)
        end = limit
        if limit < section.end:
            fragment = document.text[cursor:limit]
            boundaries = [fragment.rfind("\n\n"), fragment.rfind("\n"), fragment.rfind(". ")]
            boundary = max(boundaries)
            if boundary >= chunk_size // 2:
                end = cursor + boundary + (1 if fragment[boundary:boundary + 2] != "\n\n" else 2)
        ranges.append((cursor, end))
        if end >= section.end:
            break
        cursor = max(cursor + 1, end - overlap)
    return ranges


def structural_chunks(document: Document, chunk_size: int = 1200, overlap: int = 120) -> list[Chunk]:
    if chunk_size < 200 or not 0 <= overlap < chunk_size:
        raise ValueError("chunk_size must be >= 200 and overlap must be smaller")
    chunks: list[Chunk] = []
    for section in sections_for(document):
        for start, end in _split_structural_section(document, section, chunk_size, overlap):
            if document.text[start:end].strip():
                chunks.append(_make_chunk(document, "structure", len(chunks), start, end, section.name))
    return chunks


def chunk_documents(documents: Iterable[Document], strategy: str, chunk_size: int = 1200) -> list[Chunk]:
    if strategy not in {"fixed", "structure"}:
        raise ValueError(f"Unknown chunking strategy: {strategy}")
    function = fixed_chunks if strategy == "fixed" else structural_chunks
    return [chunk for document in documents for chunk in function(document, chunk_size=chunk_size)]
