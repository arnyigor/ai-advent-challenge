"""Тесты четырёх методов Дня 3 на fake-клиенте. Живых вызовов ноль.

Пункты 6 и 9 — защита от главного искажения дня: если хвост-контракт или
generation_config у методов различаются, сравниваются формулировки, а не методы.
"""

import pytest

import methods
from methods import (
    METHOD_RUNNERS,
    make_generation_config,
    run_cot,
    run_direct,
    run_panel,
    run_self_prompt,
)
from scoring import answer_contract

import tasks as tasks_mod
from tasks import TASKS


class FakeClient:
    """Отдаёт заранее заданные ответы по порядку вызовов."""

    def __init__(self, responses):
        # responses: список (text, finish_reason)
        self.responses = list(responses)
        self.calls = []  # (prompt, generation_config)

    def call(self, prompt, gcfg=None, system_instruction=None):
        self.calls.append((prompt, gcfg, system_instruction))
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        text, finish_reason = self.responses[idx]
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": text}]},
                    "finishReason": finish_reason,
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }


@pytest.fixture
def gcfg():
    return make_generation_config("low")


@pytest.fixture
def counting():
    return TASKS[1]  # counting-01, gold=120


def _answer_data(value):
    return f"Раccуждение…\nANSWER: {value}\n<END_RESPONSE>", "STOP"


# --- 1/2: direct и cot — количество вызовов и содержание промпта --------------


def test_direct_one_call_no_step_words(gcfg, counting):
    client = FakeClient([_answer_data("120")])
    res = run_direct(counting, client, gcfg, model="m", repeat=0)
    assert res.calls == 1
    assert res.status == "ok"
    assert res.correct
    prompt = client.calls[0][0]
    assert "пошагово" not in prompt and "шаг" not in prompt


def test_cot_one_call_has_step_instruction(gcfg, counting):
    client = FakeClient([_answer_data("120")])
    res = run_cot(counting, client, gcfg, model="m", repeat=0)
    assert res.calls == 1
    prompt = client.calls[0][0]
    assert "пошагово" in prompt
    assert answer_contract() in prompt


# --- 3/4: self_prompt чистый и загрязнённый -----------------------------------


def test_self_prompt_clean_two_calls(gcfg, counting):
    client = FakeClient(
        [
            ("Обрати внимание на кратность 3 и 5.", "STOP"),
            _answer_data("120"),
        ]
    )
    res = run_self_prompt(counting, client, gcfg, model="m")
    assert res.status == "ok"
    assert res.correct
    assert res.calls == 2


def test_self_prompt_contaminated_stops_after_first(gcfg):
    """Промпт с утёкшим эталоном: status=contaminated, второй вызов НЕ делается."""
    gold_task = next(t for t in TASKS if t.id == "logic-01")
    client = FakeClient(
        [
            ("Проверь, что на третьей позиции стоит Вера — это и есть ответ.", "STOP"),
            _answer_data("вера"),
        ]
    )
    res = run_self_prompt(gold_task, client, gcfg, model="m")
    assert res.status == "contaminated"
    assert res.calls == 1  # второй вызов не сделан
    assert res.correct is False


# --- 5/6: panel chain ----------------------------------------------------------


def test_panel_four_calls_and_role_chain(gcfg, counting):
    client = FakeClient(
        [
            ("Разбор: нужны числа, делящиеся на 3 или 5, исключая кратные 7.", "STOP"),
            ("Решение инженера: 120.", "STOP"),
            ("Проверка: подсчёт верен.", "STOP"),
            _answer_data("120"),
        ]
    )
    res = run_panel(counting, client, gcfg, model="m")
    assert res.calls == 4
    assert res.status == "ok"
    assert res.correct
    prompts = [c[0] for c in client.calls]
    # вход роли N содержит выход роли N-1
    assert "Разбор: нужны числа" in prompts[1]
    assert "Решение инженера: 120." in prompts[2]
    assert "Проверка: подсчёт верен." in prompts[3]


def test_panel_arbiter_tail_equals_direct_tail(gcfg, counting):
    direct_client = FakeClient([_answer_data("120")])
    run_direct(counting, direct_client, gcfg, model="m", repeat=0)
    panel_client = FakeClient(
        [
            ("Разбор…", "STOP"),
            ("Решение: 120.", "STOP"),
            ("Ок.", "STOP"),
            _answer_data("120"),
        ]
    )
    run_panel(counting, panel_client, gcfg, model="m", repeat=0)
    direct_prompt = direct_client.calls[0][0]
    arbiter_prompt = panel_client.calls[3][0]
    # хвост арбитра побайтно равен хвосту direct
    assert direct_prompt.endswith(answer_contract())
    assert arbiter_prompt.endswith(answer_contract())
    assert (
        direct_prompt[direct_prompt.index(answer_contract()) :]
        == arbiter_prompt[arbiter_prompt.index(answer_contract()) :]
    )


# --- 7/8: деградация -----------------------------------------------------------


def test_answer_without_marker_is_unparseable(gcfg, counting):
    client = FakeClient([("Ответ: 120", "STOP")])
    res = run_direct(counting, client, gcfg, model="m")
    assert res.status == "unparseable"
    assert res.answer_norm is None


def test_max_tokens_is_truncated(gcfg, counting):
    client = FakeClient([("Рассуждение... ANSWER: 120", "MAX_TOKENS")])
    res = run_direct(counting, client, gcfg, model="m")
    assert res.status == "truncated"
    assert res.correct is False


# --- 9: GENERATION_CONFIG идентичен у всех четырёх ------------------------------


@pytest.mark.parametrize("name", ["direct", "cot", "self_prompt", "panel"])
def test_generation_config_identical_across_methods(gcfg, counting, name):
    """Каждый вызов каждого метода получает один и тот же gcfg."""
    runner = METHOD_RUNNERS[name]
    if name == "self_prompt":
        client = FakeClient([("Разбор.", "STOP"), _answer_data("120")])
    elif name == "panel":
        client = FakeClient(
            [
                ("Разбор.", "STOP"),
                ("Решение: 120.", "STOP"),
                ("Ок.", "STOP"),
                _answer_data("120"),
            ]
        )
    else:
        client = FakeClient([_answer_data("120")])
    runner(counting, client, gcfg, model="m")
    assert client.calls
    for _prompt, cfg, _sys in client.calls:
        assert cfg == gcfg


def test_method_order_is_stable():
    assert methods.METHOD_ORDER == ["direct", "cot", "self_prompt", "panel"]
    assert set(METHOD_RUNNERS) == set(methods.METHOD_ORDER)


def test_tasks_verify_gold_passes():
    tasks_mod.verify_gold()
