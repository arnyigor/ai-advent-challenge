"""Day 23: baseline RAG versus query rewrite plus relevance filtering."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import argparse
import json
import os
from pathlib import Path
import re
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
DEFAULT_MODEL = os.environ.get("DAY23_MODEL", "deepseek:deepseek-v4-flash")
DEFAULT_TOP_K_BEFORE = int(os.environ.get("DAY23_TOP_K_BEFORE", "8"))
DEFAULT_TOP_K_AFTER = int(os.environ.get("DAY23_TOP_K_AFTER", "4"))
DEFAULT_SIMILARITY_THRESHOLD = float(os.environ.get("DAY23_SIMILARITY_THRESHOLD", "0.83"))

RAG_SYSTEM = """Ты отвечаешь на вопросы о локальном учебном проекте AI Advent.
Используй только факты из блока КОНТЕКСТ. Если данных недостаточно, прямо скажи об этом.
После ответа добавь строку «Источники:» и перечисли номера использованных фрагментов [1], [2].
Не ссылайся на фрагмент, если он не подтверждает ответ."""

REWRITE_SYSTEM = """Ты преобразуешь вопрос в один короткий запрос для семантического поиска по документации и Python-коду.
Верни только запрос, без пояснений, кавычек и ответа на вопрос.
Сохраняй точные идентификаторы, имена файлов, переменных, инструментов и коды."""


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


@dataclass(frozen=True)
class CandidateTrace:
    original_rank: int
    final_rank: int | None
    chunk_id: str
    source: str
    title: str
    section: str
    score: float
    text: str
    accepted: bool
    reason: str
    lexical_overlap: float = 0.0
    rerank_score: float = 0.0
    reranked_rank: int | None = None


def extract_answer(response) -> str:
    """Normalize the repository Client's provider-compatible response."""
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return ""
    candidate = (response.get("candidates") or [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    return "".join(str(part.get("text", "")) for part in parts if not part.get("thought")).strip()


def normalize_rewrite(value: str, original: str) -> tuple[str, bool]:
    """Return a safe single-line search query and whether fallback was required."""
    cleaned = value.strip().strip("`\"' «»")
    cleaned = re.sub(r"^(?:поисковый\s+)?запрос\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split())
    if not cleaned or len(cleaned) > 500:
        return original, True
    return cleaned, False


def format_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for item in chunks:
        blocks.append(
            f"[{item.rank}] source={item.source}\n"
            f"title={item.title}\nsection={item.section}\n{item.text.strip()}"
        )
    return "\n\n---\n\n".join(blocks)


def lexical_overlap(query: str, chunk: RetrievedChunk) -> float:
    """Measure transparent token overlap, normalizing camelCase and snake_case."""
    stopwords = {
        "как", "какой", "какая", "какие", "клиент", "день", "дня", "для", "через",
        "что", "это", "все", "весь", "получает", "получить", "использует", "работает",
    }

    def terms(value: str) -> set[str]:
        value = re.sub(r"([a-zа-я])([A-ZА-Я])", r"\1 \2", value)
        value = re.sub(r"([A-Za-zА-Яа-я])([0-9])|([0-9])([A-Za-zА-Яа-я])", lambda match: " ".join(part for part in match.groups() if part), value)
        tokens = re.findall(r"[a-zа-я0-9]+", value.casefold(), flags=re.IGNORECASE)
        return {token for token in tokens if len(token) >= 2 and token not in stopwords}

    query_terms = terms(query)
    if not query_terms:
        return 0.0
    chunk_terms = terms(f"{chunk.source} {chunk.title} {chunk.section} {chunk.text}")
    return round(len(query_terms & chunk_terms) / len(query_terms), 6)


def rerank_candidates(query: str, chunks: list[RetrievedChunk]) -> list[tuple[RetrievedChunk, float, float, int]]:
    """Blend semantic similarity with lexical evidence and return reranked rows."""
    scored = []
    for item in chunks:
        overlap = lexical_overlap(query, item)
        rerank_score = round(0.75 * item.score + 0.25 * overlap, 6)
        scored.append((item, overlap, rerank_score))
    scored.sort(key=lambda row: (-row[2], -row[0].score, row[0].chunk_id))
    return [(item, overlap, score, rank) for rank, (item, overlap, score) in enumerate(scored, 1)]


class RagAgent:
    def __init__(
        self,
        *,
        index_path: Path | str = DEFAULT_INDEX,
        model: str = DEFAULT_MODEL,
        top_k_before: int = DEFAULT_TOP_K_BEFORE,
        top_k_after: int = DEFAULT_TOP_K_AFTER,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
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
        self.top_k_before = max(1, min(int(top_k_before), 50))
        self.top_k_after = max(1, min(int(top_k_after), self.top_k_before))
        self.similarity_threshold = float(similarity_threshold)
        if not -1.0 <= self.similarity_threshold <= 1.0:
            raise ValueError("Порог similarity должен находиться в диапазоне от -1 до 1")

    @staticmethod
    def _validate_question(question: str) -> str:
        value = question.strip()
        if not value or len(value) > 1000:
            raise ValueError("Вопрос должен содержать от 1 до 1000 символов")
        return value

    def retrieve(self, query: str, *, top_k: int) -> list[RetrievedChunk]:
        vector = self.embedder.encode_query(query)
        rows = search(self.index_path, vector, top_k=top_k)
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

    def rewrite_query(self, question: str) -> tuple[str, bool]:
        try:
            response = self.llm.call(
                question,
                {"temperature": 0.0, "maxOutputTokens": 120},
                system_instruction=REWRITE_SYSTEM,
            )
            return normalize_rewrite(extract_answer(response), question)
        except Exception:
            return question, True

    def _generate(self, question: str, chunks: list[RetrievedChunk]) -> tuple[str, int]:
        prompt = f"КОНТЕКСТ:\n{format_context(chunks)}\n\nВОПРОС:\n{question}"
        response = self.llm.call(
            prompt,
            {"temperature": 0.1, "maxOutputTokens": 700},
            system_instruction=RAG_SYSTEM,
        )
        answer = extract_answer(response)
        if not answer:
            raise RuntimeError("LLM вернула пустой ответ")
        return answer, len(prompt)

    def ask_baseline(self, question: str) -> dict:
        question = self._validate_question(question)
        started = time.perf_counter()
        chunks = self.retrieve(question, top_k=self.top_k_after)
        answer, prompt_chars = self._generate(question, chunks)
        candidates = [
            CandidateTrace(
                original_rank=item.rank,
                final_rank=item.rank,
                chunk_id=item.chunk_id,
                source=item.source,
                title=item.title,
                section=item.section,
                score=item.score,
                text=item.text,
                accepted=True,
                reason="baseline: без фильтра",
                rerank_score=item.score,
                reranked_rank=item.rank,
            )
            for item in chunks
        ]
        return self._result(
            mode="baseline",
            question=question,
            search_query=question,
            rewrite_fallback=False,
            answer=answer,
            prompt_chars=prompt_chars,
            chunks=chunks,
            candidates=candidates,
            started=started,
        )

    def ask_improved(self, question: str) -> dict:
        question = self._validate_question(question)
        started = time.perf_counter()
        search_query, rewrite_fallback = self.rewrite_query(question)
        before = self.retrieve(search_query, top_k=self.top_k_before)
        accepted_before = [item for item in before if item.score >= self.similarity_threshold]
        reranked = rerank_candidates(search_query, accepted_before)
        selected = [replace(item, rank=index) for index, (item, _overlap, _score, _rank) in enumerate(reranked[: self.top_k_after], 1)]
        final_ranks = {item.chunk_id: item.rank for item in selected}
        rerank_values = {item.chunk_id: (overlap, score, rank) for item, overlap, score, rank in reranked}
        candidates = []
        for item in before:
            final_rank = final_ranks.get(item.chunk_id)
            overlap, rerank_score, reranked_rank = rerank_values.get(item.chunk_id, (0.0, item.score, None))
            if item.score < self.similarity_threshold:
                reason = f"score {item.score:.3f} < threshold {self.similarity_threshold:.3f}"
            elif final_rank is None:
                reason = f"прошёл threshold, rerank #{reranked_rank} вне top-{self.top_k_after}"
            else:
                reason = f"прошёл threshold, rerank #{reranked_rank}"
            candidates.append(
                CandidateTrace(
                    original_rank=item.rank,
                    final_rank=final_rank,
                    chunk_id=item.chunk_id,
                    source=item.source,
                    title=item.title,
                    section=item.section,
                    score=item.score,
                    text=item.text,
                    accepted=final_rank is not None,
                    reason=reason,
                    lexical_overlap=overlap,
                    rerank_score=rerank_score,
                    reranked_rank=reranked_rank,
                )
            )
        if selected:
            answer, prompt_chars = self._generate(question, selected)
        else:
            answer = "Релевантные фрагменты не найдены: все кандидаты ниже порога similarity."
            prompt_chars = 0
        return self._result(
            mode="improved",
            question=question,
            search_query=search_query,
            rewrite_fallback=rewrite_fallback,
            answer=answer,
            prompt_chars=prompt_chars,
            chunks=selected,
            candidates=candidates,
            started=started,
        )

    def _result(
        self,
        *,
        mode: str,
        question: str,
        search_query: str,
        rewrite_fallback: bool,
        answer: str,
        prompt_chars: int,
        chunks: list[RetrievedChunk],
        candidates: list[CandidateTrace],
        started: float,
    ) -> dict:
        return {
            "mode": mode,
            "question": question,
            "search_query": search_query,
            "rewrite_fallback": rewrite_fallback,
            "answer": answer,
            "model": self.model,
            "embedding_model": self.embedding_model,
            "top_k_before": self.top_k_after if mode == "baseline" else self.top_k_before,
            "top_k_after": self.top_k_after,
            "similarity_threshold": None if mode == "baseline" else self.similarity_threshold,
            "sources": [asdict(item) for item in chunks],
            "candidates": [asdict(item) for item in candidates],
            "prompt_chars": prompt_chars,
            "elapsed_sec": round(time.perf_counter() - started, 3),
        }

    def compare(self, question: str) -> dict:
        question = self._validate_question(question)
        return {
            "question": question,
            "baseline": self.ask_baseline(question),
            "improved": self.ask_improved(question),
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="Как клиент Дня 16 получает все страницы каталога tools/list?")
    parser.add_argument("--mode", choices=("baseline", "improved", "compare"), default="compare")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--top-k-before", type=int, default=DEFAULT_TOP_K_BEFORE)
    parser.add_argument("--top-k-after", type=int, default=DEFAULT_TOP_K_AFTER)
    parser.add_argument("--threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    args = parser.parse_args()
    agent = RagAgent(
        model=args.model,
        top_k_before=args.top_k_before,
        top_k_after=args.top_k_after,
        similarity_threshold=args.threshold,
    )
    if args.mode == "compare":
        result = agent.compare(args.question)
    elif args.mode == "baseline":
        result = agent.ask_baseline(args.question)
    else:
        result = agent.ask_improved(args.question)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
