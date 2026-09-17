"""Assistant with a non-bypassable invariant gate before response generation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from invariant_store import Invariant, InvariantStore


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().replace("ё", "е")).strip()


@dataclass(frozen=True)
class Check:
    invariant: Invariant
    status: str
    evidence: str

    def to_dict(self) -> dict:
        return {**self.invariant.public_dict(), "status": self.status, "evidence": self.evidence}


class InvariantGate:
    def __init__(self, store: InvariantStore):
        self.store = store

    def evaluate(self, request: str) -> tuple[int, list[Check]]:
        if not request.strip():
            raise ValueError("Запрос не должен быть пустым")
        version, invariants = self.store.load()
        normalized = _normalize(request)
        checks = []
        for invariant in invariants:
            conflict = next((term for term in invariant.conflict_terms if _normalize(term) in normalized), None)
            missing = next((term for term in invariant.required_terms if _normalize(term) not in normalized), None)
            if conflict:
                checks.append(Check(invariant, "conflict", f"Обнаружен конфликтный фрагмент: «{conflict}»"))
            elif missing:
                checks.append(Check(invariant, "conflict", f"Не выполнено обязательное условие: «{missing}»"))
            else:
                checks.append(Check(invariant, "passed", "Запрос не требует нарушения этого правила"))
        return version, checks


class InvariantAssistant:
    def __init__(self, store: InvariantStore, model_client=None):
        self.gate = InvariantGate(store)
        self.model_client = model_client

    def answer(self, request: str, history: list[dict] | None = None, *, use_model: bool = False) -> dict:
        # history is deliberately not used to obtain invariants: the contract is loaded afresh.
        version, checks = self.gate.evaluate(request)
        conflicts = [check for check in checks if check.status == "conflict"]
        trace = [check.to_dict() for check in checks]
        if conflicts:
            names = ", ".join(check.invariant.title for check in conflicts)
            details = " ".join(f"[{c.invariant.id}] {c.invariant.rule}" for c in conflicts)
            return {
                "decision": "refused", "allowed": False, "contract_version": version,
                "request": request, "reasoning": trace,
                "answer": f"Отказываюсь предлагать это решение: запрос конфликтует с инвариантами — {names}. {details} Измените запрос, сохранив эти ограничения.",
            }
        answer = "Решение допустимо. Предлагаю реализовать изменение в рамках утверждённой архитектуры, стека, технических решений и бизнес-правил; перед слиянием проверить границы слоёв и тесты."
        provider, model = "Invariant Engine", "deterministic"
        if use_model:
            if self.model_client is None:
                raise RuntimeError("Модель не настроена")
            answer = self.model_client.generate(request, trace)
            provider, model = self.model_client.provider, self.model_client.model
        return {
            "decision": "allowed", "allowed": True, "contract_version": version,
            "request": request, "reasoning": trace,
            "provider": provider, "model": model, "answer": answer,
        }
