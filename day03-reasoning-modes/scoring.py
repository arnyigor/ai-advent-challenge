"""Контракт ответа, парсер и метрики Дня 3.

Инструкция (answer_contract) и парсер живут в одном модуле намеренно: если
инструкцию правят, а парсер нет, все методы разом уходят в unparseable, и день
выброшен. Это применение правила «импортируй, не копируй» к текстовым
контрактам, а не только к константам.
"""

import re

ANSWER_MARKER = "ANSWER:"
STOP_SEQUENCE = "<END_RESPONSE>"

# Визуальные омоглифы: латинская буква -> кириллическая (после casefold).
# Модель регулярно пишет «Гaммa» с латинскими a — без замены это wrong
# при верном ответе.
_HOMOGLYPH_MAP = str.maketrans(
    "aceopxykhmbt",  # латиница
    "асеорхукнмвт",  # кириллица (12 букв)
)

_MARKDOWN_RE = re.compile(r"[*_`#]+")
_WS_RE = re.compile(r"\s+")
_SEP_RE = re.compile(r"(?<=\d)[ ,](?=\d)")  # 1 234 / 1,234 -> 1234


def normalize(s: str) -> str:
    """Нормализует и gold, и ответ модели одним способом."""
    if not s:
        return ""
    s = s.strip()
    s = _MARKDOWN_RE.sub("", s)
    s = s.strip()
    s = s.rstrip(".")  # завершающая точка
    s = _WS_RE.sub(" ", s)
    s = _SEP_RE.sub("", s)
    s = s.casefold()
    s = s.translate(_HOMOGLYPH_MAP)
    return s.strip()


def answer_contract() -> str:
    """Хвост промпта: идентичен у всех четырёх методов. Это измерительный
    инструмент дня — если у одного метода контракт иной, сравниваются
    формулировки, а не методы."""
    return (
        "\n\nЗакончи ответ ровно двумя строками:\n"
        f"{ANSWER_MARKER} <только итоговое значение, без пояснений>\n"
        f"{STOP_SEQUENCE}"
    )


def parse_answer(text: str, finish_reason: str | None) -> tuple[str, str | None]:
    """Разбирает ответ модели. Возвращает (status, answer_norm).

    Порядок проверок важен:
      1. finish_reason == MAX_TOKENS -> truncated, даже если ANSWER: распарсился
         (усечённый ответ невалиден);
      2. нет ANSWER_MARKER -> unparseable;
      3. текст берётся ПОСЛЕ последнего вхождения ANSWER_MARKER (модель может
         упомянуть слово раньше в рассуждении);
      4. обрезка по STOP_SEQUENCE, если он есть.

    Ловушка: stopSequences на уровне API вырезает маркер из ответа, поэтому
    парсер не требует наличия <END_RESPONSE> — только ANSWER:.
    """
    if finish_reason == "MAX_TOKENS":
        return "truncated", None
    if ANSWER_MARKER not in text:
        return "unparseable", None

    after = text.rsplit(ANSWER_MARKER, 1)[1]
    if STOP_SEQUENCE in after:
        after = after.split(STOP_SEQUENCE, 1)[0]

    value = normalize(after)
    if not value:
        return "unparseable", None
    return "ok", value


def accuracy(results) -> tuple[int, int]:
    """(correct, total) по не-contaminated результатам. Печатается «7/9»,
    а не проценты. contaminated исключены и показываются отдельной строкой."""
    valid = [r for r in results if getattr(r, "status", "") != "contaminated"]
    return sum(1 for r in valid if r.correct), len(valid)


def cost_per_correct(results) -> float | None:
    """Суммарные токены (prompt+output) на один верный ответ; None при 0."""
    correct, _ = accuracy(results)
    if correct == 0:
        return None
    tokens = sum(
        (getattr(r, "prompt_tokens", 0) or 0) + (getattr(r, "output_tokens", 0) or 0)
        for r in results
    )
    return round(tokens / correct, 1)


def self_consistency(results) -> float | None:
    """Доля пар повторов с совпавшим answer_norm. None при повторах <= 1.

    Именно ради этой метрики температура ненулевая: при temperature=0 все
    повторы дают одинаковый ответ и стабильность вырождается в 1.0 без смысла.
    """
    by_task = {}
    for r in results:
        if getattr(r, "status", "") != "ok":
            continue
        if r.answer_norm is None:
            continue
        by_task.setdefault(r.task_id, []).append(r.answer_norm)

    total_pairs = 0
    match_pairs = 0
    for answers in by_task.values():
        k = len(answers)
        if k < 2:
            continue
        total_pairs += k * (k - 1) // 2
        match_pairs += sum(
            1 for i in range(k) for j in range(i + 1, k) if answers[i] == answers[j]
        )
    if total_pairs == 0:
        return None
    return round(match_pairs / total_pairs, 2)
