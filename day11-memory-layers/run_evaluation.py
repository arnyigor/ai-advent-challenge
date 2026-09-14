"""Reproducible live A/B check of storage boundaries and answer influence."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DAY_DIR.parent
for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent import MemoryAgent
from memory_store import LAYERS, MemoryStore
from providers import LiveProvider


def normalized(text: str) -> str:
    """Ignore typographic spaces and dashes when checking factual values."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    return " ".join(text.split())


def evaluate(provider_id: str = "auto") -> dict:
    with tempfile.TemporaryDirectory(prefix="day11-eval-") as directory:
        store = MemoryStore(directory)
        agent = MemoryAgent(store, LiveProvider(provider_id))
        common = {"user_id": "eval-user", "task_id": "apollo"}
        store.save_fact("short", **common, session_id="full", key="кодовое_слово", value="Кедр-71")
        store.save_fact("working", **common, session_id="full", key="срок", value="15 декабря")
        store.save_fact("long", **common, session_id="full", key="стиль_ответа", value="кратко, одним предложением")
        before = store.snapshot(**common, session_id="full")
        question = "Назови кодовое слово проекта, срок и мой стиль ответа. Если сведений нет, скажи об этом."
        baseline = agent.ask(**common, session_id="baseline", user_text=question, include=())
        full = agent.ask(**common, session_id="full", user_text=question, include=LAYERS)
        baseline_text = normalized(baseline["answer"])
        full_text = normalized(full["answer"])
        other_session = store.snapshot(**common, session_id="new-session")
        other_task = store.snapshot(user_id="eval-user", session_id="new-session", task_id="other-task")
        other_user = store.snapshot(user_id="other-user", session_id="new-session", task_id="apollo")
        result = {
            "question": question,
            "stored_before_asking": before,
            "baseline": baseline,
            "with_all_layers": full,
            "isolation": {
                "new_session_has_no_short_memory": other_session["short"] == {"facts": {}, "messages": []},
                "other_task_has_no_working_memory": other_task["working"] == {},
                "other_user_has_no_long_memory": other_user["long"] == {},
                "long_memory_survives_session_change": other_session["long"] == before["long"],
            },
            "checks": {
                "code_word_in_full_answer": "кедр-71" in full_text,
                "deadline_in_full_answer": "15 декабря" in full_text,
                "style_in_full_answer": "кратко" in full_text or "одним предложением" in full_text,
                "code_word_absent_without_memory": "кедр-71" not in baseline_text,
                "deadline_absent_without_memory": "15 декабря" not in baseline_text,
            },
        }
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("auto", "deepseek", "gemini", "wormsoft"), default="auto")
    parser.add_argument("--out", type=Path, default=DAY_DIR / "results" / "evaluation.json")
    args = parser.parse_args()
    result = evaluate(args.provider)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": result["checks"], "isolation": result["isolation"], "output": str(args.out)}, ensure_ascii=False, indent=2))
    return 0 if all(result["checks"].values()) and all(result["isolation"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
