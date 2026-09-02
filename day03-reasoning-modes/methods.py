"""Четыре метода рассуждения Дня 3 за общим интерфейсом.

Все методы принимают `client.call(prompt, generation_config) -> data` и
возвращают MethodResult. Хвост answer_contract() идентичен у всех четырёх —
различается только «тело». GENERATION_CONFIG общий (см. #9 в плане тестов):
если у одного метода бюджет токенов иной, метод проигрывает по цене, а не по
качеству рассуждения.
"""

import re
import time
from dataclasses import asdict, dataclass, field

from tools.llm.gemini import extract_response, extract_usage

from scoring import STOP_SEQUENCE, answer_contract, normalize, parse_answer

#: Общий generation_config. temperature=0.7 осознанно: при 0 все повторы дают
#: одинаковый ответ и self_consistency вырождается в 1.0 без смысла.
DEFAULT_GENERATION_CONFIG = {
    "temperature": 0.7,
    # maxOutputTokens намеренно НЕ задан: лимит 4096 всё равно резал длинные
    # ответы self_prompt (Call 2/2), пусть модель отдаёт полный ответ до stop-последовательности.
    "stopSequences": [STOP_SEQUENCE],
}

_TAIL = answer_contract()

METHOD_ORDER = ["direct", "cot", "self_prompt", "panel"]

# Тексты промптов (заполняются ниже через функции-сборщики)
_SELF_PROMPT_INSTRUCTION = """Ниже — задача. Твоя цель — ТОЛЬКО составить подробный промпт-методику для другой языковой модели, которая будет её решать.
СТРОГИЕ ПРАВИЛА:
1. НЕ РЕШАЙ задачу сам.
2. Не выполняй никаких вычислений. В промпте ЗАПРЕЩЕНО писать ЛЮБЫЕ числа-значения: ни промежуточные, ни итоговый ответ, ни оценочные значения вида «около N», «примерно N», «~N», «≈N», ни проверки правдоподобности с конкретными цифрами. Ссылайся на величины словами (например, «вычисли количество делением диапазона на шаг»), но НЕ подставляй вычисленные цифры.
3. Опиши только алгоритм, шаги и то, на что обратить внимание при рассуждении.

ЗАДАЧА:
{task.prompt}"""

_COT_INSTRUCTION = """
Решай пошагово. Покажи рассуждение, затем дай итог."""

_PANEL_INSTRUCTION = """
Рассмотри задачу как группа из трёх независимых экспертов.

АНАЛИТИК:
проанализируй условия и предложи решение.

ИНЖЕНЕР:
реши задачу своим способом и объясни результат.

КРИТИК:
независимо проверь предыдущие рассуждения, укажи возможные ошибки
и дай свой вариант ответа.

После этого сопоставь три позиции и сформулируй общий итог."""


@dataclass
class StageResult:
    name: str
    status: str = "waiting"  # waiting | ok | truncated | blocked | skipped | error
    finish_reason: str | None = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class MethodResult:
    method: str
    task_id: str
    repeat: int
    status: str = (
        "error"  # ok | unparseable | truncated | blocked | contaminated | error
    )
    answer_raw: str = ""
    answer_norm: str | None = None
    correct: bool = False
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    model: str = ""
    prompts: list = field(default_factory=list)
    stages: list[StageResult] = field(default_factory=list)
    failed_stage: str | None = None

    def to_json(self) -> dict:
        data = asdict(self)
        data["tokens"] = (self.prompt_tokens or 0) + (self.output_tokens or 0)
        return data


def make_generation_config(thinking_level: str) -> dict:
    """Единственная точка сборки generation_config для всех методов."""
    cfg = dict(DEFAULT_GENERATION_CONFIG)
    cfg["thinkingConfig"] = {"thinkingLevel": thinking_level}
    return cfg


def _stage_status(text, finish_reason):
    if _is_blocked(text, finish_reason):
        return "blocked"
    if finish_reason == "MAX_TOKENS":
        return "truncated"
    return "ok"


def _emit(reporter, event) -> None:
    if reporter is not None:
        reporter.emit(event)


def _event(name, **kwargs):
    try:
        from ui import events
    except Exception:
        return None
    cls = getattr(events, name, None)
    return cls(**kwargs) if cls else None


def _one_call(client, prompt, gcfg, reporter=None, method="", stage_name=""):
    """Один вызов клиента; возвращает кортеж полей из ответа + latency."""
    t0 = time.monotonic()
    if hasattr(client, "call_stage"):
        data = client.call_stage(
            prompt,
            gcfg,
            method=method,
            stage=stage_name,
            reporter=reporter,
        )
    else:
        data = client.call(prompt, gcfg)
    latency = time.monotonic() - t0
    resp = extract_response(data)
    usage = extract_usage(data)
    return (
        resp["text"],
        resp["finish_reason"],
        usage["prompt_tokens"] or 0,
        usage["output_tokens"] or 0,
        latency,
    )


def _call_stage(client, prompt, gcfg, stage_name, reporter=None, method=""):
    ev = _event("StageStarted", method=method, stage=stage_name, prompt=prompt)
    if ev:
        _emit(reporter, ev)
    text, finish_reason, ptok, otok, latency = _one_call(
        client, prompt, gcfg, reporter=reporter, method=method, stage_name=stage_name
    )
    stage = StageResult(
        name=stage_name,
        status=_stage_status(text, finish_reason),
        finish_reason=finish_reason,
        prompt_tokens=ptok,
        output_tokens=otok,
        latency_s=round(latency, 3),
    )
    ev = _event("StageFinished", method=method, stage=stage)
    if ev:
        _emit(reporter, ev)
    return text, stage


def _is_blocked(text, finish_reason):
    return bool(finish_reason and "blockReason" in finish_reason)


def _skipped_stage(name):
    return StageResult(name=name, status="skipped")


def _failed_result(
    method,
    task,
    repeat,
    model,
    text,
    stage,
    stages,
    calls,
    ptok,
    otok,
    latency,
    prompts,
):
    return MethodResult(
        method=method,
        task_id=task.id,
        repeat=repeat,
        status=stage.status,
        answer_raw=text.strip(),
        correct=False,
        calls=calls,
        prompt_tokens=ptok,
        output_tokens=otok,
        latency_s=round(latency, 3),
        model=model,
        prompts=prompts,
        stages=stages,
        failed_stage=stage.name,
    )


def _finish(
    method,
    task,
    repeat,
    model,
    text,
    finish_reason,
    calls,
    ptok,
    otok,
    latency,
    prompts,
    stages,
):
    """Собирает MethodResult по финальному ответу метода."""
    if _is_blocked(text, finish_reason):
        status, norm = "blocked", None
    else:
        status, norm = parse_answer(text, finish_reason)
    return MethodResult(
        method=method,
        task_id=task.id,
        repeat=repeat,
        status=status,
        answer_raw=text.strip(),
        answer_norm=norm,
        correct=(status == "ok" and norm == normalize(task.gold)),
        calls=calls,
        prompt_tokens=ptok,
        output_tokens=otok,
        latency_s=round(latency, 3),
        model=model,
        prompts=prompts,
        stages=stages,
        failed_stage=None if status == "ok" else (stages[-1].name if stages else None),
    )


#: Маркеры, указывающие что рядом с эталоном стоит УТВЕРЖДАЕМЫЙ ответ,
#: а не перечисление вариантов условия.
_ANSWER_HINTS = (
    "ответ", "answer", "итог", "иском", "правильн", "значение", "результат",
    "это и есть", "выбира", "побед", "подходит", "должна быть", "должен быть",
)


def is_contaminated(prompt: str, task) -> bool:
    """Детектор утечки эталона в self_prompt.

    Сгенерированный промпт «выигрывает» жульничеством, если содержит готовый
    ответ. Для counting эталон (число) в условии отсутствует — срабатывает
    любое числовое совпадение. Для выбора из вариантов (logic/analytic) золото
    есть в условии ПО ОПРЕДЕЛЕНИЮ: перечисление опций — не утечка. Помечаем
    только если рядом с эталоном стоит ответный маркер («это и есть ответ»)."""
    if task.family == "counting" and task.gold.isdigit():
        gold_int = int(task.gold)
        # Маркеры оценочного контекста: число рядом с ними — это граница
        # правдоподобности («около 120»), а не готовый ответ, поэтому утечкой
        # не считается.
        _approx = ("около", "примерно", "приблизительно", "~", "≈", "±",
                   "не более", "менее")
        for m in re.finditer(r"\d+", prompt):
            if int(m.group()) != gold_int:
                continue
            window = prompt[max(0, m.start() - 25): m.start()]
            if any(a in window for a in _approx):
                continue
            return True
        return False
    # logic/analytic: окно вокруг эталона с ответным маркером
    gold_n = normalize(task.gold)
    pn = normalize(prompt)
    start = 0
    while True:
        idx = pn.find(gold_n, start)
        if idx == -1:
            return False
        window = pn[max(0, idx - 60): idx + len(gold_n) + 60]
        if any(hint in window for hint in _ANSWER_HINTS):
            return True
        start = idx + len(gold_n)


def run_direct(task, client, gcfg, model="", repeat=0, reporter=None):
    prompt = task.prompt + _TAIL
    text, stage = _call_stage(client, prompt, gcfg, "solve", reporter, "direct")
    return _finish(
        "direct",
        task,
        repeat,
        model,
        text,
        stage.finish_reason,
        1,
        stage.prompt_tokens,
        stage.output_tokens,
        stage.latency_s,
        [prompt],
        [stage],
    )


def run_cot(task, client, gcfg, model="", repeat=0, reporter=None):
    prompt = task.prompt + _COT_INSTRUCTION + _TAIL
    text, stage = _call_stage(client, prompt, gcfg, "reasoning", reporter, "cot")
    return _finish(
        "cot",
        task,
        repeat,
        model,
        text,
        stage.finish_reason,
        1,
        stage.prompt_tokens,
        stage.output_tokens,
        stage.latency_s,
        [prompt],
        [stage],
    )


def run_self_prompt(task, client, gcfg, model="", repeat=0, reporter=None):
    # Вызов 1: составить промпт, НЕ решать задачу.
    call1 = _SELF_PROMPT_INSTRUCTION.format(task=task)
    text1, stage1 = _call_stage(
        client, call1, gcfg, "generate_prompt", reporter, "self_prompt"
    )
    prompts = [call1]
    stages = [stage1]

    if stage1.status != "ok":
        stages.append(_skipped_stage("solve"))
        return _failed_result(
            "self_prompt",
            task,
            repeat,
            model,
            text1,
            stage1,
            stages,
            1,
            stage1.prompt_tokens,
            stage1.output_tokens,
            stage1.latency_s,
            prompts,
        )

    if is_contaminated(text1, task):
        ev = _event("StageStarted", method="self_prompt", stage="leak_check")
        if ev:
            _emit(reporter, ev)
        contaminated_stage = StageResult(
            name="leak_check",
            status="contaminated",
            finish_reason=None,
            prompt_tokens=0,
            output_tokens=0,
            latency_s=0.0,
        )
        ev = _event("StageFinished", method="self_prompt", stage=contaminated_stage)
        if ev:
            _emit(reporter, ev)
        stages.extend([contaminated_stage, _skipped_stage("solve")])
        return MethodResult(
            method="self_prompt",
            task_id=task.id,
            repeat=repeat,
            status="contaminated",
            answer_raw=text1.strip(),
            calls=1,
            prompt_tokens=stage1.prompt_tokens,
            output_tokens=stage1.output_tokens,
            latency_s=stage1.latency_s,
            model=model,
            prompts=prompts,
            stages=stages,
            failed_stage="leak_check",
        )
    ev = _event("StageStarted", method="self_prompt", stage="leak_check")
    if ev:
        _emit(reporter, ev)
    clean_stage = StageResult(name="leak_check", status="ok")
    stages.append(clean_stage)
    ev = _event("StageFinished", method="self_prompt", stage=clean_stage)
    if ev:
        _emit(reporter, ev)

    # Вызов 2: решить по сгенерированному промпту + контракт.
    call2 = (
        "Инструкция и методика решения задачи:\n"
        f"{text1.strip()}\n\n"
        "ЗАДАЧА ДЛЯ РЕШЕНИЯ:\n"
        f"{task.prompt}"
        f"{_TAIL}"
    )
    text2, stage2 = _call_stage(client, call2, gcfg, "solve", reporter, "self_prompt")
    prompts.append(call2)
    return _finish(
        "self_prompt",
        task,
        repeat,
        model,
        text2,
        stage2.finish_reason,
        2,
        stage1.prompt_tokens + stage2.prompt_tokens,
        stage1.output_tokens + stage2.output_tokens,
        stage1.latency_s + stage2.latency_s,
        prompts,
        stages + [stage2],
    )


def run_panel(task, client, gcfg, model="", repeat=0, reporter=None):
    """Группа экспертов в ОДНОМ промпте и одном вызове.

    Задание требует «создать в промпте группу экспертов и получить решение от
    каждого». Поэтому три роли (аналитик/инженер/критик) определяются внутри
    одного prompt, а модель возвращает один ответ с секциями и общим итогом.
    Хвост-контракт добавляется один раз — как у direct/cot."""
    prompt = task.prompt + _PANEL_INSTRUCTION + _TAIL
    text, stage = _call_stage(client, prompt, gcfg, "experts", reporter, "panel")
    return _finish(
        "panel",
        task,
        repeat,
        model,
        text,
        stage.finish_reason,
        1,
        stage.prompt_tokens,
        stage.output_tokens,
        stage.latency_s,
        [prompt],
        [stage],
    )


METHOD_RUNNERS = {
    "direct": run_direct,
    "cot": run_cot,
    "self_prompt": run_self_prompt,
    "panel": run_panel,
}
