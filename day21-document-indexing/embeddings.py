"""Embedding backends: a real multilingual model and an offline test fallback."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    name: str
    dimension: int

    def encode_documents(self, texts: list[str]) -> list[list[float]]: ...
    def encode_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Small deterministic fallback for tests and fully offline smoke runs."""

    def __init__(self, dimension: int = 384):
        self.name = f"hash-{dimension}"
        self.dimension = dimension

    def _encode(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        terms = re.findall(r"[\w.-]+", text.casefold(), flags=re.UNICODE)
        for term in terms:
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimension
            vector[bucket] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(text) for text in texts]

    def encode_query(self, text: str) -> list[float]:
        return self._encode(text)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str = "cpu", batch_size: int = 16):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install sentence-transformers from requirements.txt") from exc
        self.name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, device=device)
        dimension_method = getattr(self._model, "get_embedding_dimension", None)
        dimension = dimension_method() if callable(dimension_method) else self._model.get_sentence_embedding_dimension()
        if not dimension:
            raise RuntimeError("Embedding model did not report its vector dimension")
        self.dimension = int(dimension)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        values = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [row.astype("float32").tolist() for row in values]

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {text}" for text in texts])

    def encode_query(self, text: str) -> list[float]:
        return self._encode([f"query: {text}"])[0]


def create_embedder(model_name: str, device: str = "cpu") -> Embedder:
    if model_name.startswith("hash"):
        match = re.search(r"(\d+)$", model_name)
        return HashEmbedder(int(match.group(1)) if match else 384)
    return SentenceTransformerEmbedder(model_name, device=device)
