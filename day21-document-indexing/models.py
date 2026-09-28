"""Shared data contracts for the Day 21 indexing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Document:
    source: str
    title: str
    file: str
    language: str
    text: str
    content_hash: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    title: str
    file: str
    section: str
    strategy: str
    chunk_index: int
    start_char: int
    end_char: int
    text: str
    content_hash: str
    language: str
    extra: dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "title": self.title,
            "file": self.file,
            "section": self.section,
            "strategy": self.strategy,
            "chunk_index": self.chunk_index,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "char_count": len(self.text),
            "content_hash": self.content_hash,
            "language": self.language,
            **self.extra,
        }
