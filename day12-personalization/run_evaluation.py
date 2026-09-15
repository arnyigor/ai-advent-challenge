"""Live comparison: same task fact, distinct profiles, two real models."""

from __future__ import annotations

import json
import sys
from uuid import uuid4
from pathlib import Path

from personalized_agent import MemoryStore, PersonalizedAgent
from profile_store import ProfileStore
from providers import LiveProvider
from model_providers import ReasonerProvider

DAY_DIR = Path(__file__).resolve().parent
QUESTION = "Напиши фичу заметок к сроку проекта. Сформулируй решение для меня."
PROFILES = {
    "anna": {"address": "Анна", "style": "кратко и по делу", "format": "два коротких пункта", "constraints": "упомяни срок проекта", "trigger": "напиши фичу", "roles": ["analyst", "developer"]},
    "boris": {"address": "Борис", "style": "подробно и с объяснением", "format": "связный абзац", "constraints": "упомяни срок проекта", "trigger": "", "roles": []},
}


def evaluate() -> dict:
    directory = DAY_DIR / "data" / "evaluation"
    memory, profiles = MemoryStore(directory), ProfileStore(directory)
    for user, profile in PROFILES.items():
        profiles.save(user, profile)
        memory.save_fact("working", user_id=user, session_id="seed", task_id="task-1", key="срок", value="15 декабря")
    results = {}
    run_id = uuid4().hex
    for user in PROFILES:
        results[user] = {}
        for model in ("deepseek", "reasoner"):
            agent = PersonalizedAgent(memory, profiles, LiveProvider("deepseek") if model == "deepseek" else ReasonerProvider())
            results[user][model] = agent.ask(user_id=user, session_id=f"evaluation-{run_id}-{model}", task_id="task-1", user_text=QUESTION)
    checks = {
        "same_fact_for_profiles": all(result["context"]["memory_used"]["working"].get("срок") == "15 декабря" for variants in results.values() for result in variants.values()),
        "anna_workflow_on_both_models": all(result["context"]["workflow"] == ["analyst", "developer"] and len(result["steps"]) == 2 for result in results["anna"].values()),
        "boris_no_workflow": all(not result["steps"] for result in results["boris"].values()),
        "profile_isolation": all("Обращение: Борис" not in result["context"]["system"] for result in results["anna"].values()) and all("Обращение: Анна" not in result["context"]["system"] for result in results["boris"].values()),
        "same_context_per_model": all(variants["deepseek"]["context"] == variants["reasoner"]["context"] for variants in results.values()),
    }
    return {"question": QUESTION, "profiles": PROFILES, "results": results, "checks": checks}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    result = evaluate()
    target = DAY_DIR / "results" / "evaluation-two-models.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": result["checks"], "answers": {user: {model: item["answer"] for model, item in variants.items()} for user, variants in result["results"].items()}, "output": str(target)}, ensure_ascii=False, indent=2))
    return 0 if all(result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
