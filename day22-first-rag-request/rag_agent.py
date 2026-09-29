"""Day 22 agent: the same LLM with and without retrieved context."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Protocol

DAY = Path(__file__).resolve().parent
ROOT = DAY.parent
DAY21 = ROOT / "day21-document-indexing"
for path in (ROOT, DAY21):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from embeddings import create_embedder  # noqa: E402
from index_store import index_stats, search  # noqa: E402
from tools.llm.client import Client  # noqa: E402

DEFAULT_INDEX = DAY21 / "data" / "indexes" / "structure.sqlite3"
DEFAULT_MODEL = os.environ.get("DAY22_MODEL", "deepseek:deepseek-v4-flash")
DEFAULT_TOP_K = 4

SYSTEM = """Ты отвечаешь на вопросы о локальном учебном проекте AI Advent.
Отвечай по-русски, кратко и конкретно. Не придумывай неизвестные детали."""

RAG_SYSTEM = """Ты отвечаешь на вопросы о локальном учебном проекте AI Advent.
Используй только факты из блока КОНТЕКСТ. Если данных недостаточно, прямо скажи об этом.
После ответа добавь строку «Источники:» и перечисли номера использованных фрагментов [1], [2].
Не ссылайся на фрагмент, если он не подтверждает ответ."""


class TextModel(Protocol):
    model_spec: str

    def call(self, prompt: str, gcfg=None, system_instruction=None): ...


@dataclass(frozen=True)
class RetrievedChunk:
    rank: int
    chunk_id: str
    source: str
    title: str
    section: str
    score: float
    text: str


def format_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for item in chunks:
        blocks.append(
            f"[{item.rank}] source={item.source}\n"
            f"title={item.title}\nsection={item.section}\n{item.text.strip()}"
        )
    return "\n\n---\n\n".join(blocks)


def extract_answer(response) -> str:
    """Normalize the repository Client's provider-compatible response."""
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return ""
    candidate = (response.get("candidates") or [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    return "".join(str(part.get("text", "")) for part in parts if not part.get("thought")).strip()


class RagAgent:
    def __init__(
        self,
        *,
        index_path: Path | str = DEFAULT_INDEX,
        model: str = DEFAULT_MODEL,
        top_k: int = DEFAULT_TOP_K,
        embedder=None,
        llm: TextModel | None = None,
    ):
        self.index_path = Path(index_path).resolve()
        if not self.index_path.is_file():
            raise FileNotFoundError(
                f"Индекс не найден: {self.index_path}. Сначала запустите pipeline.py Дня 21."
            )
        stats = index_stats(self.index_path)
        self.embedding_model = stats["embedding_model"]
        self.embedder = embedder or create_embedder(self.embedding_model)
        if self.embedder.dimension != stats["embedding_dim"]:
            raise ValueError("Embedding-модель не соответствует размерности индекса")
        self.llm = llm or Client(model, quiet=True)
        self.model = getattr(self.llm, "model_spec", model)
        self.top_k = max(1, min(int(top_k), 10))

    def retrieve(self, question: str) -> list[RetrievedChunk]:
        vector = self.embedder.encode_query(question)
        rows = search(self.index_path, vector, top_k=self.top_k)
        return [
            RetrievedChunk(
                rank=index,
                chunk_id=row["chunk_id"],
                source=row["source"],
                title=row["title"],
                section=row["section"],
                score=row["score"],
                text=row["text"],
            )
            for index, row in enumerate(rows, 1)
        ]

    def ask(self, question: str, *, use_rag: bool) -> dict:
        question = question.strip()
        if not question or len(question) > 1000:
            raise ValueError("Вопрос должен содержать от 1 до 1000 символов")
        started = time.perf_counter()
        chunks: list[RetrievedChunk] = []
        if use_rag:
            chunks = self.retrieve(question)
            prompt = f"КОНТЕКСТ:\n{format_context(chunks)}\n\nВОПРОС:\n{question}"
            system = RAG_SYSTEM
        else:
            prompt = question
            system = SYSTEM
        response = self.llm.call(
            prompt,
            {"temperature": 0.1, "maxOutputTokens": 700},
            system_instruction=system,
        )
        answer = extract_answer(response)
        if not answer:
            raise RuntimeError("LLM вернула пустой ответ")
        return {
            "mode": "rag" if use_rag else "plain",
            "question": question,
            "answer": answer,
            "model": self.model,
            "embedding_model": self.embedding_model if use_rag else None,
            "sources": [asdict(item) for item in chunks],
            "prompt_chars": len(prompt),
            "elapsed_sec": round(time.perf_counter() - started, 3),
        }

    def compare(self, question: str) -> dict:
        plain = self.ask(question, use_rag=False)
        rag = self.ask(question, use_rag=True)
        return {"question": question.strip(), "plain": plain, "rag": rag}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="Какой аварийный код у проекта Atlas и когда его разрешено использовать?")
    parser.add_argument("--mode", choices=("plain", "rag", "compare"), default="compare")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = parser.parse_args()
    agent = RagAgent(model=args.model, top_k=args.top_k)
    result = agent.compare(args.question) if args.mode == "compare" else agent.ask(args.question, use_rag=args.mode == "rag")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
