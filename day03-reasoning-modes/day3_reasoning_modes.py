"""Day 3 — Reasoning Modes: direct / cot / self_prompt / panel (chain).

Сравнение четырёх способов рассуждения на трёх задачах (по одному инстансу
на семейство) с повторами. Одна модель на всю матрицу; fallback — как в day2:
если модель отвалилась посреди, вся матрица перезапускается на следующей
(иначе методы сравнивались бы на разных моделях).

Бюджет: direct+cot+self_prompt+panel = 1+1+2+4 = 8 вызовов на (задачу, повтор).
3 задачи x 3 повтора x 8 = 72. Пейсер --rpm 12 → ~10 минут основного прогона.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tools.llm.gemini import (
    MODEL_CHAIN,
    GeminiRetryableError,
    ModelUnavailableError,
    call_gemini_with_retries,
    has_gemini_api_key,
)
from tools.llm.ui import (
    BOLD,
    RED,
    RESET,
    YELLOW,
    print_box,
    scene,
    wait_for_enter,
)

from methods import METHOD_ORDER, METHOD_RUNNERS, make_generation_config
from scoring import accuracy, cost_per_correct, self_consistency
from tasks import TASKS, verify_gold


def _retry_logger(message):
    print(f"{YELLOW}  {message}{RESET}")


class Pacer:
    """Минимальный пейсер: gap между вызовами по rpm."""

    def __init__(self, rpm):
        self.gap = 60.0 / rpm if rpm and rpm > 0 else 0.0
        self._last = None

    def wait(self):
        now = time.monotonic()
        if self._last is not None and self.gap:
            d = self.gap - (now - self._last)
            if d > 0:
                time.sleep(d)
        self._last = time.monotonic()


class Client:
    """Привязывает одну модель к вызовам; применяет пейсер и ретраи."""

    def __init__(self, model, pacer, quiet):
        self.model = model
        self.pacer = pacer
        self.quiet = quiet

    def call(self, prompt, gcfg=None, system_instruction=None):
        if self.pacer:
            self.pacer.wait()
        return call_gemini_with_retries(
            self.model,
            prompt,
            gcfg,
            system_instruction=system_instruction,
            quiet=self.quiet,
            retry_logger=None if self.quiet else _retry_logger,
        )


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------


def run_matrix(repeats, methods, tasks, model, gcfg, pacer, quiet):
    """repeat -> task -> method: повтор снаружи, чтобы деградация модели во
    времени не била систематически по одному методу."""
    results = []
    for repeat in range(repeats):
        for task in tasks:
            for name in methods:
                runner = METHOD_RUNNERS[name]
                results.append(
                    runner(
                        task,
                        Client(model, pacer, quiet),
                        gcfg,
                        model=model,
                        repeat=repeat,
                    )
                )
    return results


def run_with_fallback(repeats, methods, tasks, model_chain, gcfg, rpm, quiet):
    attempts = []
    pacer = Pacer(rpm)
    for model in model_chain:
        try:
            results = run_matrix(repeats, methods, tasks, model, gcfg, pacer, quiet)
            return results, model, attempts
        except (ModelUnavailableError, GeminiRetryableError) as e:
            attempts.append({"model": model, "status": "failed", "error": str(e)[:200]})
            if not quiet:
                print(f"{YELLOW}  [{model}] недоступна: {e}{RESET}")
    raise RuntimeError(
        f"Все модели в цепочке недоступны: {json.dumps(attempts, ensure_ascii=False)}"
    )


# ---------------------------------------------------------------------------
# Агрегация и метрики
# ---------------------------------------------------------------------------


def aggregate(results, methods, tasks):
    """Строит по-методную статистику с фиксированным каркасом для JSON."""
    base = {}
    for name in METHOD_ORDER:
        rows = [r for r in results if r.method == name]
        fam = {}
        for t in tasks:
            frows = [r for r in rows if r.task_id == t.id]
            c, total = accuracy(frows)
            fam[t.family] = {"correct": c, "total": total}
        c, total = accuracy(rows)
        base[name] = {
            "families": fam,
            "total": {"correct": c, "total": total},
            "calls": sum(r.calls for r in rows),
            "tokens": sum(
                (r.prompt_tokens or 0) + (r.output_tokens or 0) for r in rows
            ),
            "cost_per_correct": cost_per_correct(rows),
            "self_consistency": self_consistency(rows),
        }
    return base


def failure_counts(results):
    counts = {
        "wrong": 0,
        "unparseable": 0,
        "truncated": 0,
        "blocked": 0,
        "contaminated": 0,
        "error": 0,
    }
    for r in results:
        if r.status == "ok":
            if not r.correct:
                counts["wrong"] += 1
        elif r.status in counts:
            counts[r.status] += 1
        else:
            counts["error"] += 1
    return counts


def verdict(agg, methods, threshold=2):
    """Финальный вердикт с порогом значимости."""
    ranked = sorted(
        ((m, agg[m]["total"]) for m in methods),
        key=lambda kv: kv[1]["correct"],
        reverse=True,
    )
    if not ranked or ranked[0][1]["total"] == 0:
        return None
    best_name, best = ranked[0]
    if len(ranked) > 1:
        second = ranked[1][1]["correct"]
        if best["correct"] - second < threshold:
            return (
                f"Методы неразличимы на этом объёме: разрыв между лучшим "
                f"({best_name}) и вторым < {threshold} попаданий из "
                f"{best['total']}."
            )
    return f"Лучший метод: {best_name} ({best['correct']}/{best['total']})."


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------


def print_intro(repeats, thinking, methods, rpm):
    print()
    print_box([f"{BOLD}AI Advent Challenge — Day 03{RESET}", "Reasoning Modes"])
    print()
    print(f"Repeats: {repeats}")
    print(f"Thinking level: {thinking}")
    print(f"Methods: {', '.join(methods)}")
    if rpm:
        print(f"Pacer: {rpm} RPM")
    print()
    for t in TASKS:
        b = t.baseline()
        baseline_txt = f"~{b:.0%}" if b else "~0%"
        print(f"  {t.id:12} family={t.family:9} baseline={baseline_txt}")
    print()


def print_tasks():
    for i, t in enumerate(TASKS, 1):
        print()
        print_box([f"{BOLD}ЗАДАЧА {i} ({t.id}, {t.family}){RESET}"])
        print()
        print(t.prompt)
        print()


def print_representative(results, methods):
    """Показывает по одному ответу на метод (первый repeat первой задачи),
    без дополнительных вызовов к API."""
    for name in methods:
        row = next((r for r in results if r.method == name), None)
        if row is None:
            continue
        print()
        print_box([f"{BOLD}МЕТОД: {name}{RESET}", f"calls={row.calls}"])
        print()
        if row.prompts:
            print("Промпт (фрагмент):")
            print(row.prompts[0][:400])
            print()
        print("Ответ:")
        print(row.answer_raw[:400] or "(пустой)")
        print()


def print_matrix(agg, methods):
    print()
    scene("day3.matrix")
    print_box(["МАТРИЦА ТОЧНОСТИ"])
    print()
    header = f"{'':<14}" + "".join(
        f"{fam:>11}" for fam in ["logic", "counting", "analytic", "ИТОГО", "baseline"]
    )
    print(header)
    print("─" * 66)
    baselines = {t.family: t.baseline() for t in TASKS}
    for name in methods:
        a = agg[name]
        cells = [
            f"{a['families'][f]['correct']}/{a['families'][f]['total']}"
            for f in ["logic", "counting", "analytic"]
        ]
        tot = a["total"]
        row = f"{name:<14}" + "".join(f"{c:>11}" for c in cells)
        row += f"{tot['correct']}/{tot['total']:>6}"
        base = (
            f"~{sum(baselines.values()) / len(baselines):.0%}" if tot["total"] else "-"
        )
        row += f"{base:>10}"
        print(row)


def print_cost(agg, methods):
    print()
    print_box(["СТАБИЛЬНОСТЬ И ЦЕНА"])
    print()
    header = (
        f"{'':<14}{'self-cons':>11}{'вызовов':>10}{'токены':>11}{'на 1 верный':>13}"
    )
    print(header)
    print("─" * 66)
    for name in methods:
        a = agg[name]
        sc = a["self_consistency"]
        sc_txt = "-" if sc is None else f"{sc:.2f}"
        cpc = a["cost_per_correct"]
        cpc_txt = "-" if cpc is None else str(int(cpc))
        print(f"{name:<14}{sc_txt:>11}{a['calls']:>10}{a['tokens']:>11}{cpc_txt:>13}")


def print_failures(counts):
    print()
    parts = " | ".join(f"{k} {v}" for k, v in counts.items())
    print(f"ПРОВАЛЫ: {parts}")
    print()


def print_verdict(v):
    print()
    scene("day3.verdict")
    print_box([f"{BOLD}ВЫВОД{RESET}"])
    print(v or "(нет данных)")


def print_scene_banner(label):
    print()
    print_box([f"{BOLD}{label}{RESET}"])


# ---------------------------------------------------------------------------
# JSON (фиксированная схема при любом исходе)
# ---------------------------------------------------------------------------


def build_json_document(
    repeats,
    thinking,
    rpm,
    methods,
    tasks,
    model_chain,
    agg,
    failures,
    model_used,
    attempts=None,
    error=None,
    v=None,
):
    doc = {
        "day": 3,
        "model_chain": model_chain,
        "model_used": model_used,
        "attempts": attempts or [],
        "error": error,
        "repeats": repeats,
        "thinking_level": thinking,
        "rpm": rpm,
        "methods": methods,
        "tasks": [
            {"id": t.id, "family": t.family, "gold": t.gold, "baseline": t.baseline()}
            for t in tasks
        ],
        "matrix": agg,
        "failures": failures,
        "verdict": v,
    }
    return doc


def run_json_mode(repeats, thinking, rpm, methods, tasks, model_chain, quiet=True):
    if not has_gemini_api_key():
        doc = build_json_document(
            repeats,
            thinking,
            rpm,
            methods,
            tasks,
            model_chain,
            aggregate([], methods, tasks),
            failure_counts([]),
            None,
            error="GEMINI_API_KEY not set",
        )
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        sys.exit(1)

    gcfg = make_generation_config(thinking)
    try:
        results, model_used, attempts = run_with_fallback(
            repeats, methods, tasks, model_chain, gcfg, rpm, quiet
        )
    except RuntimeError as e:
        doc = build_json_document(
            repeats,
            thinking,
            rpm,
            methods,
            tasks,
            model_chain,
            aggregate([], methods, tasks),
            failure_counts([]),
            None,
            error=str(e),
        )
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        sys.exit(1)

    agg = aggregate(results, methods, tasks)
    fail = failure_counts(results)
    v = verdict(agg, methods)
    doc = build_json_document(
        repeats,
        thinking,
        rpm,
        methods,
        tasks,
        model_chain,
        agg,
        fail,
        model_used,
        attempts=attempts,
        v=v,
    )
    print(json.dumps(doc, ensure_ascii=False, indent=2))


def run_text_mode(repeats, thinking, rpm, methods, tasks, model_chain, interactive):
    if not has_gemini_api_key():
        print(f"{RED}[ERROR]{RESET} GEMINI_API_KEY не найден в переменных окружения.")
        sys.exit(1)

    verify_gold()
    print_intro(repeats, thinking, methods, rpm)
    scene("day3.intro")
    if interactive:
        wait_for_enter()

    print_scene_banner("ЗАДАЧИ")
    scene("day3.tasks")
    print_tasks()
    if interactive:
        wait_for_enter("Нажмите Enter для запуска матрицы методов...")

    gcfg = make_generation_config(thinking)
    try:
        results, model_used, attempts = run_with_fallback(
            repeats, methods, tasks, model_chain, gcfg, rpm, quiet=False
        )
    except RuntimeError as e:
        print(f"\n{RED}[ERROR]{RESET} Запрос не выполнен: {e}")
        sys.exit(1)

    if attempts:
        print()
        print(f"{YELLOW}[FALLBACK]{RESET} Использована модель: {model_used}")

    print_scene_banner("ОТВЕТЫ МЕТОДОВ (примеры)")
    scene("day3.methods")
    print_representative(results, methods)

    agg = aggregate(results, methods, tasks)
    fail = failure_counts(results)
    v = verdict(agg, methods)

    print_matrix(agg, methods)
    print_cost(agg, methods)
    print_failures(fail)
    print_verdict(v)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description="Day 3 — Reasoning Modes")
    parser.add_argument("--mode", choices=["text", "json"], default="text")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--rpm", type=float, default=12.0, help="лимит запросов в минуту (пейсер)"
    )
    parser.add_argument("--methods", default="direct,cot,self_prompt,panel")
    parser.add_argument("--thinking", choices=["low", "high"], default="low")
    parser.add_argument(
        "--model",
        default=None,
        help=f"зафиксировать одну модель (по умолчанию цепочка: {', '.join(MODEL_CHAIN)})",
    )
    parser.add_argument("--no-interactive", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = set(methods) - set(METHOD_ORDER)
    if unknown:
        raise SystemExit(f"Неизвестные методы: {sorted(unknown)}")
    model_chain = [args.model] if args.model else MODEL_CHAIN
    if args.mode == "json":
        run_json_mode(
            args.repeats, args.thinking, args.rpm, methods, TASKS, model_chain
        )
    else:
        run_text_mode(
            args.repeats,
            args.thinking,
            args.rpm,
            methods,
            TASKS,
            model_chain,
            interactive=not args.no_interactive,
        )


if __name__ == "__main__":
    main()
