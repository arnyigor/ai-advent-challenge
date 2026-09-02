"""Схема JSON Дня 3: набор ключей идентичен при любом исходе.

Наследует дисциплину day2: структура документа одинакова для успеха, ошибки
и запуска с одним методом — иначе машинная обработка результатов между днями
невозможна.
"""

import json

import day3_reasoning_modes as day3
from day3_reasoning_modes import build_json_document
from tasks import TASKS

from methods import METHOD_ORDER


def _key_tree(obj):
    """Рекурсивное множество ключей (листья/списки помечаются маркером)."""
    if isinstance(obj, dict):
        return {k: _key_tree(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return ("<list>", [_key_tree(x) for x in obj][:1] if obj else ())
    return "<leaf>"


def _sample_agg_full():
    """Имитация агрегата от успешного прогона всех методов (3 задачи x 3 повтора)."""
    calls_per_unit = {"direct": 1, "cot": 1, "self_prompt": 2, "panel": 4}
    agg = {}
    for name in METHOD_ORDER:
        fam = {f: {"correct": 1, "total": 3} for f in ("logic", "counting", "analytic")}
        agg[name] = {
            "families": fam,
            "total": {"correct": 3, "total": 9},
            "calls": calls_per_unit[name] * 3 * 3,
            "tokens": 1200,
            "cost_per_correct": 300.0,
            "self_consistency": 0.67,
        }
    return agg


def _failures_zero():
    return {
        "wrong": 0,
        "unparseable": 0,
        "truncated": 0,
        "blocked": 0,
        "contaminated": 0,
        "error": 0,
    }


def test_schema_success_vs_error_key_sets_equal():
    ok_doc = build_json_document(
        repeats=3,
        thinking="low",
        rpm=12,
        methods=METHOD_ORDER,
        tasks=TASKS,
        model_chain=["m1"],
        agg=_sample_agg_full(),
        failures=_failures_zero(),
        model_used="m1",
        attempts=[],
        error=None,
        v="Лучший: direct (5/9).",
    )
    err_doc = build_json_document(
        repeats=3,
        thinking="low",
        rpm=12,
        methods=METHOD_ORDER,
        tasks=TASKS,
        model_chain=["m1"],
        agg=day3.aggregate([], METHOD_ORDER, TASKS),
        failures=_failures_zero(),
        model_used=None,
        error="GEMINI_API_KEY not set",
        v=None,
    )
    assert _key_tree(ok_doc) == _key_tree(err_doc)


def test_schema_single_method_has_same_structure():
    """--methods direct: отсутствующие методы остаются в схеме с пустыми/нулевыми
    значениями (агрегат строит каркас по METHOD_ORDER)."""
    methods = ["direct"]
    doc = build_json_document(
        repeats=1,
        thinking="low",
        rpm=12,
        methods=methods,
        tasks=TASKS,
        model_chain=["m1"],
        agg=day3.aggregate([], methods, TASKS),
        failures=_failures_zero(),
        model_used=None,
        error=None,
        v=None,
    )
    # структура ключей не зависит от числа выбранных методов
    assert _key_tree(doc) == _key_tree(
        build_json_document(
            repeats=3,
            thinking="low",
            rpm=12,
            methods=METHOD_ORDER,
            tasks=TASKS,
            model_chain=["m1"],
            agg=day3.aggregate([], METHOD_ORDER, TASKS),
            failures=_failures_zero(),
            model_used=None,
            error=None,
            v=None,
        )
    )


def test_build_document_aggregate_cardinality():
    """calls == суммарное число вызовов: direct=1, cot=1, self_prompt=2, panel=4."""
    agg = _sample_agg_full()
    expected = {"direct": 1, "cot": 1, "self_prompt": 2, "panel": 4}
    for name, calls in expected.items():
        assert agg[name]["calls"] == calls * 3 * 3  # вызовы на задачу*повтор


def test_json_document_roundtrip_serializable():
    doc = build_json_document(
        repeats=1,
        thinking="high",
        rpm=0,
        methods=["direct"],
        tasks=TASKS,
        model_chain=["m1"],
        agg=day3.aggregate([], ["direct"], TASKS),
        failures=_failures_zero(),
        model_used=None,
        error="boom",
        v=None,
    )
    json.dumps(doc, ensure_ascii=False)  # не должно бросить
