"""Three context strategies for Day 10, without any summarisation.

Полный transcript всегда остаётся источником правды в SQLite. Здесь решается
только одно: какие сообщения уходят в запрос к модели.

* ``sliding``   — последние N сообщений, остальное отбрасывается;
* ``facts``     — блок «ключ: значение» + последние N сообщений;
* ``branching`` — вся история активной ветки (что за история, а не сколько).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Callable, Mapping, Sequence


STRATEGIES = ("sliding", "facts", "branching")

STRATEGY_LABELS = {
    "sliding": "Sliding Window",
    "facts": "Sticky Facts",
    "branching": "Branching",
}

FACTS_PREFIX = (
    "Проверенная память о диалоге в формате «ключ: значение». Считай её "
    "надёжной: эти факты подтверждены пользователем, даже если соответствующих "
    "сообщений больше нет в переданной истории.\n"
)

# Ключи фиксируем, иначе извлекатель плодит синонимы («цель» / «задача» /
# «что делаем») и facts перестают перезаписываться.
FACT_KEYS = (
    "проект",
    "цель",
    "платформа",
    "бюджет",
    "срок",
    "ограничение",
    "предпочтение",
    "решение",
    "договорённость",
    "формат_сдачи",
    "контакт",
)

FACTS_SYSTEM_PROMPT = (
    "Ты — модуль памяти диалога. Не отвечай пользователю и ничего не объясняй. "
    "Возвращай только JSON-объект с фактами."
)

MAX_FACT_KEYS = 40
MAX_FACT_VALUE_CHARS = 400


@dataclass(frozen=True)
class FactsState:
    """Ключ-значение память. ``revision`` растёт на каждое изменение."""

    values: dict = field(default_factory=dict)
    revision: int = 0
    usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        return "\n".join(f"- {key}: {value}" for key, value in self.values.items())

    def merge(self, updates: Mapping[str, object], usage: dict | None = None) -> FactsState:
        """Возвращает новое состояние. Память только дополняется и
        перезаписывается: удалять факты извлекателю нельзя.

        Удаление по пустому значению здесь было и оказалось footgun'ом — модель
        периодически «прибирала» факты, которые считала неактуальными, и они
        молча пропадали из памяти. Перезаписи хватает для изменившихся решений.
        """
        merged = dict(self.values)
        changed = False
        for raw_key, raw_value in updates.items():
            key = normalize_fact_key(raw_key)
            if not key:
                continue
            value = normalize_fact_value(raw_value)
            if not value:
                continue
            if merged.get(key) != value:
                if key not in merged and len(merged) >= MAX_FACT_KEYS:
                    continue
                merged[key] = value
                changed = True
        if not changed:
            return self
        return FactsState(
            values=merged,
            revision=self.revision + 1,
            usage=dict(usage or {}),
        )


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "sliding"
    recent_messages: int = 6

    def __post_init__(self) -> None:
        if self.name not in STRATEGIES:
            allowed = ", ".join(STRATEGIES)
            raise ValueError(f"strategy должна быть одной из: {allowed}")
        if isinstance(self.recent_messages, bool) or not isinstance(self.recent_messages, int):
            raise TypeError("recent_messages должен быть целым числом")
        if not 1 <= self.recent_messages <= 1_000:
            raise ValueError("recent_messages должен быть от 1 до 1000")

    @property
    def label(self) -> str:
        return STRATEGY_LABELS[self.name]

    @property
    def uses_facts(self) -> bool:
        return self.name == "facts"

    @property
    def uses_window(self) -> bool:
        """Branching отдаёт ветку целиком — окно к ней не применяется."""
        return self.name in ("sliding", "facts")


@dataclass(frozen=True)
class ContextView:
    messages: tuple
    dropped_message_count: int
    verbatim_message_count: int
    facts: FactsState

    def metadata(self) -> dict:
        return {
            "dropped_message_count": self.dropped_message_count,
            "verbatim_message_count": self.verbatim_message_count,
            "facts": self.facts.to_dict(),
        }


def normalize_fact_key(raw: object) -> str:
    key = re.sub(r"\s+", "_", str(raw or "").strip().lower())
    key = re.sub(r"[^0-9a-zа-яё_]", "", key)
    return key[:60]


def normalize_fact_value(raw: object) -> str:
    if raw is None or isinstance(raw, (dict, list)):
        # Вложенные структуры приходят от моделей регулярно; плоская память
        # честнее, чем json.dumps-строка, которую потом никто не прочитает.
        value = "" if raw is None else json.dumps(raw, ensure_ascii=False)
    elif isinstance(raw, bool):
        value = "да" if raw else "нет"
    else:
        value = str(raw)
    value = re.sub(r"\s+", " ", value).strip()
    if value.lower() in {"", "null", "none", "нет данных", "неизвестно", "-", "—"}:
        return ""
    return value[:MAX_FACT_VALUE_CHARS]


def build_context(
    history: Sequence,
    config: StrategyConfig,
    facts: FactsState,
    message_factory: Callable[[str, str], object],
) -> ContextView:
    """Собирает то, что реально уйдёт в запрос, по выбранной стратегии."""
    if config.uses_window:
        tail = tuple(history[-config.recent_messages :]) if config.recent_messages else ()
    else:
        tail = tuple(history)
    dropped = len(history) - len(tail)

    messages = tail
    if config.uses_facts and facts.values:
        messages = (message_factory("system", FACTS_PREFIX + facts.render()), *tail)
    return ContextView(
        messages=messages,
        dropped_message_count=dropped,
        verbatim_message_count=len(tail),
        facts=facts if config.uses_facts else FactsState(),
    )


def render_facts_prompt(facts: FactsState, user_message: str) -> str:
    known = facts.render() or "(пока пусто)"
    keys = ", ".join(FACT_KEYS)
    return (
        "Обнови память диалога по новому сообщению пользователя.\n"
        "Верни ТОЛЬКО JSON-объект вида {\"ключ\": \"значение\"} с фактами, "
        "которые нужно добавить или изменить. Ничего не выдумывай: бери только "
        "то, что прямо сказано в сообщении. Если менять нечего — верни {}.\n"
        "Ничего не удаляй: чтобы изменить решение, верни тот же ключ с новым "
        "значением.\n"
        f"Предпочитай эти ключи, если подходят по смыслу: {keys}. "
        "Если факт не ложится ни в один — придумай короткий ключ на русском "
        "в нижнем регистре, одно-два слова через подчёркивание.\n\n"
        f"Текущая память:\n{known}\n\n"
        f"Новое сообщение пользователя:\n{user_message}"
    )


def parse_facts_response(text: object) -> dict:
    """Достаёт JSON-объект из ответа модели. Мусор — не ошибка, а пустой апдейт."""
    if not isinstance(text, str):
        return {}
    payload = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", payload, re.DOTALL)
    if fenced:
        payload = fenced.group(1).strip()
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(payload[start : end + 1])
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _demo() -> None:
    class M:
        def __init__(self, role, content):
            self.role, self.content = role, content

        def __eq__(self, other):
            return (self.role, self.content) == (other.role, other.content)

    history = [M("user", f"m{i}") for i in range(10)]

    sliding = build_context(history, StrategyConfig("sliding", 4), FactsState(), M)
    assert [m.content for m in sliding.messages] == ["m6", "m7", "m8", "m9"]
    assert sliding.dropped_message_count == 6

    facts = FactsState().merge({"Цель ": "  сделать   ТЗ ", "бюджет": 480000, "шум": None})
    assert facts.values == {"цель": "сделать ТЗ", "бюджет": "480000"}, facts.values
    assert facts.revision == 1
    assert facts.merge({"цель": "сделать ТЗ"}) is facts  # без изменений — без ревизии
    assert facts.merge({"бюджет": ""}) is facts  # пустое значение не удаляет факт
    assert facts.merge({"бюджет": 520000}).values["бюджет"] == "520000"  # перезапись

    view = build_context(history, StrategyConfig("facts", 4), facts, M)
    assert view.messages[0].role == "system" and "бюджет: 480000" in view.messages[0].content
    assert len(view.messages) == 5

    branch = build_context(history, StrategyConfig("branching", 4), facts, M)
    assert len(branch.messages) == 10 and branch.dropped_message_count == 0

    assert parse_facts_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_facts_response("не знаю") == {}
    assert parse_facts_response('текст {"город": "Казань"} хвост') == {"город": "Казань"}
    print("strategies self-check OK")


if __name__ == "__main__":
    _demo()
