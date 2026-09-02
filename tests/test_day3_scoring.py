"""Табличные тесты парсера/нормализатора Дня 3 + метрики.

Парсер и answer_contract лежат в одном модуле (scoring.py): если контракт
правят, а парсер нет, все методы уходят в unparseable — тест 1 страхует именно
от этого рассинхрона.
"""

import pytest

from scoring import (
    ANSWER_MARKER,
    STOP_SEQUENCE,
    accuracy,
    answer_contract,
    cost_per_correct,
    normalize,
    parse_answer,
    self_consistency,
)


# --- табличный тест парсера ---------------------------------------------------


@pytest.mark.parametrize(
    "text,finish_reason,expected",
    [
        ("ANSWER: 120\n<END_RESPONSE>", "STOP", ("ok", "120")),
        ("ANSWER: 120", "STOP", ("ok", "120")),  # маркер вырезан API
        ("ANSWER: **Гамма**", "STOP", ("ok", "гамма")),
        ("ANSWER: Гамма.", "STOP", ("ok", "гамма")),
        ("ANSWER:Гамма", "STOP", ("ok", "гамма")),
        ("рассуждение ANSWER: неверно… ANSWER: 120", "STOP", ("ok", "120")),
        ("ANSWER: Гaммa", "STOP", ("ok", "гамма")),  # латинские a
        ("текст без маркера", "STOP", ("unparseable", None)),
        ("ANSWER: 120", "MAX_TOKENS", ("truncated", None)),
        ("ANSWER:", "STOP", ("unparseable", None)),
        ("```\nANSWER: 120\n```", "STOP", ("ok", "120")),
        ("ANSWER: Вера", "STOP", ("ok", "вера")),
        ("ANSWER: Bера", "STOP", ("ok", "вера")),  # латинская B
        ("ANSWER: 1 234", "STOP", ("ok", "1234")),
    ],
)
def test_parse_answer(text, finish_reason, expected):
    assert parse_answer(text, finish_reason) == expected


# --- инварианты нормализатора --------------------------------------------------


def test_normalize_idempotent():
    for x in ["  Гамма.  ", "**вера**", "120", "Гaммa", "Aнна"]:
        assert normalize(normalize(x)) == normalize(x)


def test_normalize_no_false_positives():
    assert normalize("120") != normalize("1120")
    assert normalize("да") != normalize("нет")
    assert normalize("вера") != normalize("вера2")


# --- контракт и парсер не разошлись -------------------------------------------


def test_answer_contract_contains_both_markers():
    contract = answer_contract()
    assert ANSWER_MARKER in contract
    assert STOP_SEQUENCE in contract


def test_parse_answer_accepts_response_without_stop_marker():
    """stopSequences вырезает <END_RESPONSE> из ответа — его отсутствие норма."""
    assert parse_answer("ANSWER: 120", "STOP") == ("ok", "120")


def test_normalize_gold_matches_option_names():
    """gold и варианты должны сравниваться после normalize (омоглифы, регистр)."""
    for gold, option in [("вера", "Вера"), ("гамма", "Гaммa"), ("аня", "Aня")]:
        assert normalize(gold) == normalize(option)


# --- метрики -------------------------------------------------------------------


class _R:
    def __init__(
        self,
        task_id="t1",
        status="ok",
        answer_norm=None,
        correct=False,
        prompt_tokens=10,
        output_tokens=5,
    ):
        self.task_id = task_id
        self.status = status
        self.answer_norm = answer_norm
        self.correct = correct
        self.prompt_tokens = prompt_tokens
        self.output_tokens = output_tokens


def test_accuracy_excludes_contaminated():
    rows = [
        _R(status="ok", correct=True),
        _R(status="ok", correct=False),
        _R(status="contaminated", correct=True),
    ]
    assert accuracy(rows) == (1, 2)


def test_cost_per_correct_none_when_zero_correct():
    rows = [_R(status="ok", correct=False)]
    assert cost_per_correct(rows) is None


def test_cost_per_correct_rounds():
    rows = [_R(status="ok", correct=True, prompt_tokens=100, output_tokens=24)]
    assert cost_per_correct(rows) == 124.0


def test_self_consistency_none_for_single_repeat():
    assert self_consistency([_R(status="ok", answer_norm="x")]) is None


def test_self_consistency_agreement_ratio():
    rows = [
        _R(answer_norm="a"),
        _R(answer_norm="a"),
        _R(answer_norm="b"),  # 2 совп. из 3 пар
        _R(task_id="t2", answer_norm="c"),
        _R(task_id="t2", answer_norm="c"),  # 1 из 1
    ]
    # t1: 3 ответа -> 3 пары, совпало 1 (a,a); t2: 1 пара совпала -> всего 2/4
    assert self_consistency(rows) == 0.5
