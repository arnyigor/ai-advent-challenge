"""Четыре метода рассуждения Дня 3 за общим интерфейсом.

Все методы принимают `client.call(prompt, generation_config) -> data` и
возвращают MethodResult. Хвост answer_contract() идентичен у всех четырёх —
различается только «тело». GENERATION_CONFIG общий (см. #9 в плане тестов):
если у одного метода бюджет токенов иной, метод проигрывает по цене, а не по
качеству рассуждения.
"""

import re
import time
from dataclasses import dataclass, field

from tools.llm.gemini import extract_response, extract_usage

from scoring import STOP_SEQUENCE, answer_contract, normalize, parse_answer

#: Общий generation_config. temperature=0.7 осознанно: при 0 все повторы дают
#: одинаковый ответ и self_consistency вырождается в 1.0 без смысла.
DEFAULT_GENERATION_CONFIG = {
    "temperature": 0.7,
    "maxOutputTokens": 2048,  # self_prompt режется на 1024 (живой прогон); лимит общий
    "stopSequences": [STOP_SEQUENCE],
}

_TAIL = answer_contract()

METHOD_ORDER = ["direct", "cot", "self_prompt", "panel"]

# Тексты промптов (заполняются ниже через функции-сборщики)
_SELF_PROMPT_INSTRUCTION = """Ниже — задача. НЕ решай её. Составь подробный промпт,
который поможет языковой модели решить её максимально надёжно.
Опиши, на что обратить внимание и в каком порядке рассуждать.
Не приводи ответ и не выполняй вычисления.

ЗАДАЧА:
{task.prompt}"""

_COT_INSTRUCTION = """
Решай пошагово. Покажи рассуждение, затем дай итог."""


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


def make_generation_config(thinking_level: str) -> dict:
    """Единственная точка сборки generation_config для всех методов."""
    cfg = dict(DEFAULT_GENERATION_CONFIG)
    cfg["thinkingConfig"] = {"thinkingLevel": thinking_level}
    return cfg


def _one_call(client, prompt, gcfg):
    """Один вызов клиента; возвращает кортеж полей из ответа + latency."""
    t0 = time.monotonic()
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


def _is_blocked(text, finish_reason):
    return bool(finish_reason and "blockReason" in finish_reason)


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
        for token in re.findall(r"\d+", prompt):
            if int(token) == gold_int:
                return True
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


def run_direct(task, client, gcfg, model="", repeat=0):
    prompt = task.prompt + "\n\nРеши задачу." + _TAIL
    text, fr, pt, ot, lat = _one_call(client, prompt, gcfg)
    return _finish("direct", task, repeat, model, text, fr, 1, pt, ot, lat, [prompt])


def run_cot(task, client, gcfg, model="", repeat=0):
    prompt = task.prompt + _COT_INSTRUCTION + _TAIL
    text, fr, pt, ot, lat = _one_call(client, prompt, gcfg)
    return _finish("cot", task, repeat, model, text, fr, 1, pt, ot, lat, [prompt])


def run_self_prompt(task, client, gcfg, model="", repeat=0):
    # Вызов 1: составить промпт, НЕ решать задачу.
    call1 = _SELF_PROMPT_INSTRUCTION.format(task=task)
    text1, _fr, pt1, ot1, lat1 = _one_call(client, call1, gcfg)
    prompts = [call1]

    if is_contaminated(text1, task):
        return MethodResult(
            method="self_prompt",
            task_id=task.id,
            repeat=repeat,
            status="contaminated",
            answer_raw=text1.strip(),
            calls=1,
            prompt_tokens=pt1,
            output_tokens=ot1,
            latency_s=round(lat1, 3),
            model=model,
            prompts=prompts,
        )

    # Вызов 2: решить по сгенерированному промпту + контракт.
    call2 = text1.strip() + "\n\nЗАДАЧА:\n" + task.prompt + _TAIL
    text2, fr2, pt2, ot2, lat2 = _one_call(client, call2, gcfg)
    prompts.append(call2)
    return _finish(
        "self_prompt",
        task,
        repeat,
        model,
        text2,
        fr2,
        2,
        pt1 + pt2,
        ot1 + ot2,
        lat1 + lat2,
        prompts,
    )


def run_panel(task, client, gcfg, model="", repeat=0):
    """Цепочка ролей: аналитик -> инженер -> критик -> арбитр.

    Хвост-контракт добавляется только арбитру (единственный вызов, который
    производит финальный ответ). Инвариант «одинаковый контракт» при этом не
    нарушается: сравнение идёт по финальным ответам."""
    prompts = []

    analyst = f"""Ты — аналитик. Разбери условие задачи: выпиши ограничения, варианты и величины. НЕ решай задачу и не называй итоговый ответ.

ЗАДАЧА:
{task.prompt}"""
    text_a, _, pt_a, ot_a, lat_a = _one_call(client, analyst, gcfg)
    prompts.append(analyst)

    engineer = f"""Ты — инженер. Реши задачу на основе разбора аналитика.

ЗАДАЧА:
{task.prompt}

РАЗБОР АНАЛИТИКА:
{text_a.strip()}"""
    text_e, _, pt_e, ot_e, lat_e = _one_call(client, engineer, gcfg)
    prompts.append(engineer)

    critic = f"""Ты — критик. Проверь решение инженера: найди ошибку или подтверди его. Укажи конкретно, что неверно, если ошибка есть. Итоговый ответ не называй.

ЗАДАЧА:
{task.prompt}

РАЗБОР АНАЛИТИКА:
{text_a.strip()}

РЕШЕНИЕ ИНЖЕНЕРА:
{text_e.strip()}"""
    text_c, _, pt_c, ot_c, lat_c = _one_call(client, critic, gcfg)
    prompts.append(critic)

    arbiter = (
        f"""Ты — арбитр. На основе разбора, решения и проверки вынеси итоговое значение.

ЗАДАЧА:
{task.prompt}

РАЗБОР АНАЛИТИКА:
{text_a.strip()}

РЕШЕНИЕ ИНЖЕНЕРА:
{text_e.strip()}

ПРОВЕРКА КРИТИКА:
{text_c.strip()}
"""
        + _TAIL
    )
    text_f, fr_f, pt_f, ot_f, lat_f = _one_call(client, arbiter, gcfg)
    prompts.append(arbiter)

    return _finish(
        "panel",
        task,
        repeat,
        model,
        text_f,
        fr_f,
        4,
        pt_a + pt_e + pt_c + pt_f,
        ot_a + ot_e + ot_c + ot_f,
        lat_a + lat_e + lat_c + lat_f,
        prompts,
    )


METHOD_RUNNERS = {
    "direct": run_direct,
    "cot": run_cot,
    "self_prompt": run_self_prompt,
    "panel": run_panel,
}
