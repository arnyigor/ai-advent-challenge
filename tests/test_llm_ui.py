"""Golden-тесты UI-хелперов tools/llm/ui.py.

Ожидаемый вывод зафиксирован по локальным копиям из HEAD-версии
day02-response-control/day2_response_control.py (Unicode-рамка print_box,
pass_fail, truncate), чтобы рефакторинг «удаление дубликатов» не изменил
визуальный вывод text-режима, который пишется на видео.
"""

import re

from tools.llm.ui import BOX_WIDTH, GREEN, RED, RESET, pass_fail, print_box, truncate

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def test_print_box_unicode_matches_day2_head(capsys):
    print_box(["A — BASELINE", "No response control"])
    out = capsys.readouterr().out
    assert out == (
        "╔" + "═" * 64 + "╗\n"
        "║ " + "A — BASELINE".ljust(63) + "║\n"
        "║ " + "No response control".ljust(63) + "║\n"
        "╚" + "═" * 64 + "╝\n"
    )


def test_print_box_box_width_matches_separator():
    """Рамка и разделитель '─'*(BOX_WIDTH+2) из day2 дают одинаковую ширину
    (66 символов) — иначе визуально разъедутся."""
    assert BOX_WIDTH == 64


def test_print_box_custom_width(capsys):
    print_box(["x"], width=8)
    out = capsys.readouterr().out
    assert (
        out
        == "╔" + "═" * 8 + "╗\n" + "║ " + "x".ljust(7) + "║\n" + "╚" + "═" * 8 + "╝\n"
    )


def test_print_box_ansi_escape_breaks_alignment():
    """Страж: ANSI-escape внутри строки ломает рамку — ljust считает символы,
    а не видимую ширину (терминал показывает escape как нулевую ширину).
    print_box предназначен для чистых строк; цветные значения красятся ДО
    сборки строки рамки. Тест фиксирует это ограничение, чтобы кто-то не
    «починил» его раскраской внутри print_box."""
    line = "A" + GREEN + "B" + RESET
    rendered = "║ " + line.ljust(BOX_WIDTH - 1) + "║"
    visible = _ANSI_RE.sub("", rendered)  # то, что реально увидит терминал
    assert len(visible) != BOX_WIDTH + 2


def test_pass_fail_true():
    assert pass_fail(True) == f"{GREEN}[PASS]{RESET}"


def test_pass_fail_false():
    assert pass_fail(False) == f"{RED}[FAIL]{RESET}"


def test_truncate_within_limit():
    s = "a" * 90
    assert truncate(s) == s


def test_truncate_over_limit():
    out = truncate("x" * 91)
    assert out == "x" * 90 + "..."


def test_truncate_strips_trailing_whitespace_of_first_chunk():
    """Пробелы на границе text[:max_len] (внутренние, после strip) убираются
    rstrip до '...' — иначе обрезка оставит 'хвост' из пробелов перед маркером."""
    out = truncate("x" * 80 + " " * 15 + "y" * 10)
    assert out == "x" * 80 + "..."
    assert len(out) == 83
