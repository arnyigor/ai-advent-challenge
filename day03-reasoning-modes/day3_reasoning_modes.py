"""Day 3 — Reasoning Modes: direct / cot / self_prompt / panel (expert group).

Сравнение четырёх способов рассуждения на трёх задачах (по одному инстансу
на семейство) с повторами. Одна модель на всю матрицу; fallback — как в day2:
если модель отвалилась посреди, вся матрица перезапускается на следующей
(иначе методы сравнивались бы на разных моделях).

Бюджет: direct+cot+self_prompt+panel = 1+1+2+1 = 5 вызовов на (задачу, повтор).
3 задачи x 3 повтора x 5 = 45. Пейсер --rpm 12 → ~4 минуты основного прогона.
"""

import argparse
from contextlib import nullcontext
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
    GeminiCancelledError,
    GeminiRetryableError,
    ModelUnavailableError,
    call_gemini_stream_with_retries,
    call_gemini_with_retries,
    has_gemini_api_key,
)
from tools.llm.deepseek import (
    DEFAULT_MODEL as DEEPSEEK_DEFAULT_MODEL,
    DeepSeekCancelledError,
    DeepSeekModelUnavailableError,
    DeepSeekRetryableError,
    call_deepseek_stream_with_retries,
    call_deepseek_with_retries,
    has_deepseek_api_key,
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
from methods import MethodResult, StageResult
from scoring import accuracy, cost_per_correct, self_consistency
from tasks import TASKS, verify_gold
from ui.events import (
    ExperimentFinished,
    ExperimentStarted,
    FallbackTriggered,
    MethodFinished,
    MethodStarted,
    NullReporter,
    RequestRetrying,
    RequestStateChanged,
    StageOutputDelta,
    TaskStarted,
)


def _retry_logger(message):
    print(f"{YELLOW}  {message}{RESET}")


def split_model_spec(model_spec):
    if isinstance(model_spec, str) and ":" in model_spec:
        provider, model = model_spec.split(":", 1)
        return provider.strip().lower(), model.strip()
    return "gemini", model_spec


def model_label(model_spec):
    provider, model = split_model_spec(model_spec)
    return model if provider == "gemini" else f"{provider}:{model}"


def _has_key_for_model(model_spec):
    provider, _model = split_model_spec(model_spec)
    if provider == "deepseek":
        return has_deepseek_api_key()
    return has_gemini_api_key()


def _missing_key_message(model_spec):
    provider, _model = split_model_spec(model_spec)
    if provider == "deepseek":
        return "DEEPSEEK_API_KEY is not set"
    return "GEMINI_API_KEY is not set"


class Pacer:
    """Минимальный пейсер: gap между вызовами по rpm."""

    def __init__(self, rpm, cancel_event=None):
        self.gap = 60.0 / rpm if rpm and rpm > 0 else 0.0
        self._last = None
        self.cancel_event = cancel_event

    def wait(self):
        now = time.monotonic()
        if self._last is not None and self.gap:
            d = self.gap - (now - self._last)
            if d > 0:
                if self.cancel_event is not None:
                    if self.cancel_event.wait(d):
                        raise RunCancelled()
                else:
                    time.sleep(d)
        self._last = time.monotonic()


class Client:
    """Привязывает одну модель к вызовам; применяет пейсер и ретраи."""

    def __init__(self, model, pacer, quiet, cancel_event=None, stream=False):
        self.provider, parsed_model = split_model_spec(model)
        self.model = parsed_model or (
            DEEPSEEK_DEFAULT_MODEL if self.provider == "deepseek" else model
        )
        self.model_spec = model_label(f"{self.provider}:{self.model}")
        self.pacer = pacer
        self.quiet = quiet
        self.cancel_event = cancel_event
        self.stream = stream

    def call(self, prompt, gcfg=None, system_instruction=None):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RunCancelled()
        if self.pacer:
            self.pacer.wait()
        try:
            if self.provider == "deepseek":
                return call_deepseek_with_retries(
                    self.model,
                    prompt,
                    gcfg,
                    system_instruction=system_instruction,
                    quiet=self.quiet,
                    retry_logger=None if self.quiet else _retry_logger,
                    cancel_event=self.cancel_event,
                )
            if self.provider == "gemini":
                return call_gemini_with_retries(
                    self.model,
                    prompt,
                    gcfg,
                    system_instruction=system_instruction,
                    quiet=self.quiet,
                    retry_logger=None if self.quiet else _retry_logger,
                    cancel_event=self.cancel_event,
                )
            raise RuntimeError(f"Unknown LLM provider: {self.provider}")
        except (GeminiCancelledError, DeepSeekCancelledError):
            raise RunCancelled() from None

    def call_stage(
        self,
        prompt,
        gcfg=None,
        method="",
        stage="",
        reporter=None,
        system_instruction=None,
    ):
        if not self.stream:
            return self.call(prompt, gcfg, system_instruction=system_instruction)
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RunCancelled()
        if self.pacer:
            self.pacer.wait()

        def emit(event):
            if reporter is not None:
                reporter.emit(event)

        try:
            callbacks = {
                "on_state": lambda state: emit(
                    RequestStateChanged(method=method, stage=stage, state=state)
                ),
                "on_text": lambda text: emit(
                    StageOutputDelta(method=method, stage=stage, text=text)
                ),
                "on_retry": lambda attempt, wait_s, reason: emit(
                    RequestRetrying(
                        method=method,
                        stage=stage,
                        attempt=attempt,
                        wait_s=wait_s,
                        reason=reason[:200],
                    )
                ),
            }
            if self.provider == "deepseek":
                return call_deepseek_stream_with_retries(
                    self.model,
                    prompt,
                    gcfg,
                    system_instruction=system_instruction,
                    quiet=self.quiet,
                    retry_logger=None if self.quiet else _retry_logger,
                    cancel_event=self.cancel_event,
                    **callbacks,
                )
            if self.provider == "gemini":
                return call_gemini_stream_with_retries(
                    self.model,
                    prompt,
                    gcfg,
                    system_instruction=system_instruction,
                    quiet=self.quiet,
                    retry_logger=None if self.quiet else _retry_logger,
                    cancel_event=self.cancel_event,
                    **callbacks,
                )
            raise RuntimeError(f"Unknown LLM provider: {self.provider}")
        except (GeminiCancelledError, DeepSeekCancelledError):
            raise RunCancelled() from None


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------


CALLS_PER_METHOD = {"direct": 1, "cot": 1, "self_prompt": 2, "panel": 1}


class RunCancelled(RuntimeError):
    """Кооперативная отмена: поднимается между вызовами/стадиями, а не внутри
    уже выполняющегося синхронного HTTP-запроса."""


def estimate_calls(repeats, methods, tasks):
    return repeats * len(tasks) * sum(CALLS_PER_METHOD.get(m, 1) for m in methods)


def run_matrix(
    repeats,
    methods,
    tasks,
    model,
    gcfg,
    pacer,
    quiet,
    reporter=None,
    cancel_event=None,
    stream=False,
):
    """repeat -> task -> method: повтор снаружи, чтобы деградация модели во
    времени не била систематически по одному методу."""
    reporter = reporter or NullReporter()
    results = []
    reporter.emit(
        ExperimentStarted(
            model=model,
            thinking=(gcfg.get("thinkingConfig") or {}).get("thinkingLevel", "-"),
            repeats=repeats,
            tasks_total=len(tasks),
            methods=list(methods),
            total_calls_estimate=estimate_calls(repeats, methods, tasks),
        )
    )
    for repeat in range(repeats):
        for task_index, task in enumerate(tasks, 1):
            if cancel_event is not None and cancel_event.is_set():
                raise RunCancelled()
            reporter.emit(
                TaskStarted(
                    task_id=task.id,
                    family=task.family,
                    prompt=task.prompt,
                    repeat=repeat,
                    repeat_total=repeats,
                    task_index=task_index,
                    task_total=len(tasks),
                    baseline=task.baseline(),
                )
            )
            for name in methods:
                if cancel_event is not None and cancel_event.is_set():
                    raise RunCancelled()
                runner = METHOD_RUNNERS[name]
                reporter.emit(MethodStarted(method=name))
                result = runner(
                    task,
                    Client(
                        model,
                        pacer,
                        quiet,
                        cancel_event=cancel_event,
                        stream=stream,
                    ),
                    gcfg,
                    model=model,
                    repeat=repeat,
                    reporter=reporter,
                )
                results.append(result)
                reporter.emit(MethodFinished(result=result))
    reporter.emit(ExperimentFinished(results=results, model=model))
    return results


def run_with_fallback(
    repeats,
    methods,
    tasks,
    model_chain,
    gcfg,
    rpm,
    quiet,
    reporter=None,
    cancel_event=None,
    stream=False,
):
    reporter = reporter or NullReporter()
    attempts = []
    pacer = Pacer(rpm, cancel_event=cancel_event)
    for index, model in enumerate(model_chain):
        try:
            results = run_matrix(
                repeats,
                methods,
                tasks,
                model,
                gcfg,
                pacer,
                quiet,
                reporter=reporter,
                cancel_event=cancel_event,
                stream=stream,
            )
            return results, model_label(model), attempts
        except (
            ModelUnavailableError,
            GeminiRetryableError,
            DeepSeekModelUnavailableError,
            DeepSeekRetryableError,
        ) as e:
            attempts.append({"model": model, "status": "failed", "error": str(e)[:200]})
            next_model = (
                model_chain[index + 1] if index + 1 < len(model_chain) else None
            )
            reporter.emit(
                FallbackTriggered(
                    old_model=model,
                    new_model=next_model,
                    reason=str(e)[:200],
                )
            )
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
    results=None,
    attempts=None,
    error=None,
    v=None,
):
    results = results or []
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
        "runs": [r.to_json() for r in results],
        "matrix": agg,
        "failures": failures,
        "verdict": v,
    }
    return doc


def _result_from_json(row):
    stages = [StageResult(**s) for s in row.get("stages", [])]
    allowed = {
        "method",
        "task_id",
        "repeat",
        "status",
        "answer_raw",
        "answer_norm",
        "correct",
        "calls",
        "prompt_tokens",
        "output_tokens",
        "latency_s",
        "model",
        "prompts",
        "failed_stage",
    }
    data = {k: row.get(k) for k in allowed if k in row}
    return MethodResult(**data, stages=stages)


def load_results_document(path):
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    return doc, [_result_from_json(row) for row in doc.get("runs", [])]


def write_json_document(path, doc):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")


def run_json_mode(
    repeats, thinking, rpm, methods, tasks, model_chain, quiet=True, out_path=None
):
    verify_gold()
    primary_model = model_chain[0] if model_chain else None
    if not _has_key_for_model(primary_model):
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
            error=_missing_key_message(primary_model),
        )
        if out_path:
            write_json_document(out_path, doc)
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
        if out_path:
            write_json_document(out_path, doc)
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
        results=results,
        attempts=attempts,
        v=v,
    )
    if out_path:
        write_json_document(out_path, doc)
    print(json.dumps(doc, ensure_ascii=False, indent=2))


def _resolve_ui(ui):
    if ui != "auto":
        return ui
    return "dashboard" if sys.stdout.isatty() else "plain"


def _make_reporter(ui, methods, tasks, video_mode=False, video_columns=None):
    if ui == "none":
        return NullReporter(), nullcontext()
    if ui == "dashboard":
        try:
            from ui.dashboard import DashboardReporter

            reporter = DashboardReporter(
                methods, tasks, video_mode=video_mode, width=video_columns
            )
            return reporter, reporter
        except ImportError:
            from ui.plain import PlainReporter

            return PlainReporter(), nullcontext()
    from ui.plain import PlainReporter

    return PlainReporter(), nullcontext()


def run_text_mode(
    repeats,
    thinking,
    rpm,
    methods,
    tasks,
    model_chain,
    interactive,
    ui="auto",
    out_path=None,
    video_mode=False,
    video_columns=None,
):
    primary_model = model_chain[0] if model_chain else None
    if not _has_key_for_model(primary_model):
        print(f"{RED}[ERROR]{RESET} {_missing_key_message(primary_model)} в переменных окружения.")
        sys.exit(1)

    verify_gold()
    ui = _resolve_ui(ui)
    if ui == "plain":
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
    reporter, reporter_context = _make_reporter(
        ui, methods, tasks, video_mode=video_mode, video_columns=video_columns
    )
    try:
        with reporter_context:
            results, model_used, attempts = run_with_fallback(
                repeats,
                methods,
                tasks,
                model_chain,
                gcfg,
                rpm,
                quiet=(ui == "dashboard"),
                reporter=reporter,
            )
    except RuntimeError as e:
        print(f"\n{RED}[ERROR]{RESET} Запрос не выполнен: {e}")
        sys.exit(1)

    if attempts and ui == "plain":
        print()
        print(f"{YELLOW}[FALLBACK]{RESET} Использована модель: {model_used}")

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
        results=results,
        attempts=attempts,
        v=v,
    )
    if out_path:
        write_json_document(out_path, doc)

    if ui == "plain":
        print_scene_banner("ОТВЕТЫ МЕТОДОВ (примеры)")
        scene("day3.methods")
        print_representative(results, methods)

        print_matrix(agg, methods)
        print_cost(agg, methods)
        print_failures(fail)
        print_verdict(v)
    elif ui == "none":
        print(json.dumps(doc, ensure_ascii=False, indent=2))


def replay_results(path, ui, methods=None, video_mode=False, video_columns=None):
    from ui.events import StageFinished, StageStarted

    doc, results = load_results_document(path)
    methods = methods or doc.get("methods") or METHOD_ORDER
    selected = [r for r in results if r.method in methods]
    tasks_by_id = {t.id: t for t in TASKS}
    repeats = doc.get("repeats") or (max((r.repeat for r in selected), default=-1) + 1)
    reporter, reporter_context = _make_reporter(
        _resolve_ui(ui),
        methods,
        TASKS,
        video_mode=video_mode,
        video_columns=video_columns,
    )
    model = doc.get("model_used") or "-"
    thinking = doc.get("thinking_level") or "-"

    with reporter_context:
        reporter.emit(
            ExperimentStarted(
                model=model,
                thinking=thinking,
                repeats=repeats,
                tasks_total=len(TASKS),
                methods=list(methods),
                total_calls_estimate=estimate_calls(repeats, methods, TASKS),
            )
        )
        order = {task.id: i for i, task in enumerate(TASKS)}
        selected.sort(
            key=lambda r: (r.repeat, order.get(r.task_id, 999), methods.index(r.method))
        )
        grouped = {}
        for result in selected:
            grouped.setdefault((result.repeat, result.task_id), []).append(result)

        for (repeat, task_id), group in grouped.items():
            task = tasks_by_id.get(task_id)
            if task is None:
                continue
            reporter.emit(
                TaskStarted(
                    task_id=task.id,
                    family=task.family,
                    prompt=task.prompt,
                    repeat=repeat,
                    repeat_total=repeats,
                    task_index=TASKS.index(task) + 1,
                    task_total=len(TASKS),
                    baseline=task.baseline(),
                )
            )
            for result in group:
                reporter.emit(MethodStarted(method=result.method))
                for stage in result.stages:
                    reporter.emit(StageStarted(method=result.method, stage=stage.name))
                    reporter.emit(StageFinished(method=result.method, stage=stage))
                reporter.emit(MethodFinished(result=result))
        reporter.emit(ExperimentFinished(results=selected, model=model))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description="Day 3 — Reasoning Modes")
    parser.add_argument("--mode", choices=["text", "json"], default="text")
    parser.add_argument(
        "--ui",
        choices=["auto", "dashboard", "plain", "none"],
        default="auto",
        help="интерфейс для text/replay режима",
    )
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
    parser.add_argument("--out", default=None, help="сохранить полный JSON run")
    parser.add_argument(
        "--replay-results",
        default=None,
        help="отрисовать сохранённый JSON без API-вызовов",
    )
    parser.add_argument("--video-mode", action="store_true")
    parser.add_argument("--video-columns", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = set(methods) - set(METHOD_ORDER)
    if unknown:
        raise SystemExit(f"Неизвестные методы: {sorted(unknown)}")
    if args.replay_results:
        replay_results(
            args.replay_results,
            args.ui,
            methods=methods,
            video_mode=args.video_mode,
            video_columns=args.video_columns,
        )
        return
    model_chain = [args.model] if args.model else MODEL_CHAIN
    if args.mode == "json":
        run_json_mode(
            args.repeats,
            args.thinking,
            args.rpm,
            methods,
            TASKS,
            model_chain,
            out_path=args.out,
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
            ui=args.ui,
            out_path=args.out,
            video_mode=args.video_mode,
            video_columns=args.video_columns,
        )


if __name__ == "__main__":
    main()
