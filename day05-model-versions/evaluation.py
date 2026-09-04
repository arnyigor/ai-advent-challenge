"""Safe-ish, deterministic evaluator for the Day 5 generated function."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys


TOTAL_TESTS = 10
FORBIDDEN_CALLS = {"eval", "exec", "open", "compile", "__import__", "input", "breakpoint"}
ALLOWED_IMPORTS = {"typing", "collections", "bisect"}


def extract_python(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n([\s\S]*?)```", text, re.IGNORECASE)
    for block in blocks:
        if "def reconcile_ranges" in block:
            return block.strip()
    match = re.search(r"(^def\s+reconcile_ranges\b[\s\S]*)", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def validate_candidate(code: str) -> tuple[bool, str]:
    if not code:
        return False, "Функция reconcile_ranges не найдена"
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] not in ALLOWED_IMPORTS for alias in node.names):
                return False, "Импорт не входит в безопасный allowlist"
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
            return False, "Импорт не входит в безопасный allowlist"
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
            return False, f"Запрещённое имя: {node.id}"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return False, "Dunder-атрибуты запрещены"
    return True, "ok"


_HARNESS = r'''
import json

tests = []

def case(name, fn):
    try:
        fn()
        tests.append({"name": name, "passed": True})
    except Exception as exc:
        tests.append({"name": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"[:240]})

def eq(actual, expected):
    if actual != expected:
        raise AssertionError(f"{actual!r} != {expected!r}")

def raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("ожидался ValueError")

case("empty", lambda: eq(reconcile_ranges([], []), []))
case("merge_overlap_and_adjacent", lambda: eq(
    reconcile_ranges([(10, 12), (1, 5), (4, 8), (8, 9)], []),
    [(1, 9), (10, 12)]
))
case("split_by_exclusions", lambda: eq(
    reconcile_ranges([(1, 10)], [(3, 5), (7, 12)]),
    [(1, 3), (5, 7)]
))
case("normalize_both_sides", lambda: eq(
    reconcile_ranges([(5, 9), (1, 4), (3, 7)], [(2, 3), (3, 5), (20, 30)]),
    [(1, 2), (5, 9)]
))
case("outside_and_touching_exclusions", lambda: eq(
    reconcile_ranges([(10, 20)], [(1, 10), (20, 30)]),
    [(10, 20)]
))
case("fully_excluded", lambda: eq(
    reconcile_ranges([(2, 4), (8, 12)], [(0, 20)]),
    []
))

def mutation_test():
    ranges = [(9, 12), (1, 5)]
    exclusions = [(3, 4)]
    before = (ranges[:], exclusions[:])
    reconcile_ranges(ranges, exclusions)
    eq((ranges, exclusions), before)
case("does_not_mutate", mutation_test)

case("invalid_empty_interval", lambda: raises_value_error(
    lambda: reconcile_ranges([(1, 1)], [])
))
case("invalid_reversed_exclusion", lambda: raises_value_error(
    lambda: reconcile_ranges([(1, 2)], [(5, 4)])
))

def type_validation():
    raises_value_error(lambda: reconcile_ranges([(True, 2)], []))
    raises_value_error(lambda: reconcile_ranges([(1.0, 2)], []))
case("strict_integer_validation", type_validation)

print(json.dumps({"tests": tests}, ensure_ascii=False))
'''


def evaluate_answer(text: str, timeout_s: float = 5.0) -> dict:
    code = extract_python(text)
    safe, reason = validate_candidate(code)
    if not safe:
        return {
            "code_found": bool(code),
            "safe": False,
            "passed": 0,
            "total": TOTAL_TESTS,
            "score": 0.0,
            "error": reason,
            "tests": [],
        }
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-c", code + "\n" + _HARNESS],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "code_found": True, "safe": True, "passed": 0, "total": TOTAL_TESTS,
            "score": 0.0, "error": "Таймаут тестов", "tests": [],
        }
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    if not payload:
        error = (proc.stderr or proc.stdout or "Нет результата тестов")[-500:]
        return {
            "code_found": True, "safe": True, "passed": 0, "total": TOTAL_TESTS,
            "score": 0.0, "error": error, "tests": [],
        }
    tests = payload["tests"]
    passed = sum(1 for item in tests if item["passed"])
    return {
        "code_found": True,
        "safe": True,
        "passed": passed,
        "total": TOTAL_TESTS,
        "score": passed / TOTAL_TESTS,
        "error": None,
        "tests": tests,
    }
