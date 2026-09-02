"""Задачи Дня 3: три семейства по одному инстансу, эталоны проверены кодом.

Никакого генератора: задач три, каждая с программной проверкой verify_gold(),
которая запускается при каждом старте скрипта ДО сетевых вызовов. Если эталон
разошёлся с условием — падаем с внятным сообщением, а не отдаём невалидный
эксперимент.

Политика утечки эталона разная по семействам:
  counting — эталон (число) НЕ должен встречаться в тексте условия;
  logic/analytic — ответ является выбором из перечисленных вариантов, поэтому
  эталон присутствует в условии ПО ОПРЕДЕЛЕНИЮ; baseline угадывания 1/N.
"""

from dataclasses import dataclass
from itertools import permutations

NAMES = ("Аня", "Борис", "Вера", "Глеб", "Дина")

LOGIC_PROMPT = """\
Пять человек стоят в очереди на позициях с 1 по 5: Аня, Борис, Вера, Глеб, Дина.
Известно:
1. Вера стоит непосредственно перед Глебом.
2. Аня стоит позже Бориса (не обязательно сразу за ним).
3. Дина не стоит на краю очереди (не первая и не последняя).
4. Между Борисом и Верой стоит ровно один человек.
5. Глеб не второй.
Кто стоит на третьей позиции?"""

COUNTING_PROMPT = """\
Сколько целых чисел от 1 до 300 включительно делятся на 3 или на 5,
но при этом не делятся на 7?"""

ANALYTIC_PROMPT = """\
Выбирается подрядчик по трём критериям с весами:
цена — 0.4, скорость — 0.35, поддержка — 0.25.
Оценки по 10-балльной шкале:
Альфа:  цена 6, скорость 9, поддержка 4
Бета:   цена 8, скорость 6, поддержка 7
Гамма:  цена 7, скорость 7, поддержка 9
Какой подрядчик набирает наибольший взвешенный балл?"""


@dataclass(frozen=True)
class Task:
    id: str
    family: str  # logic | counting | analytic
    prompt: str
    gold: str  # уже нормализованный
    options: tuple[str, ...] | None = None

    def baseline(self) -> float:
        """Baseline случайного угадывания: 1/N для выбора, ~0 для счёта."""
        if self.options:
            return 1.0 / len(self.options)
        return 0.0


TASKS = [
    Task(
        id="logic-01",
        family="logic",
        prompt=LOGIC_PROMPT,
        gold="вера",
        options=tuple(n.lower() for n in NAMES),
    ),
    Task(
        id="counting-01",
        family="counting",
        prompt=COUNTING_PROMPT,
        gold="120",
        options=None,
    ),
    Task(
        id="analytic-01",
        family="analytic",
        prompt=ANALYTIC_PROMPT,
        gold="гамма",
        options=("альфа", "бета", "гамма"),
    ),
]


def _logic_solutions():
    """Все расстановки имён, удовлетворяющие пяти ограничениям очереди."""
    solutions = []
    for order in permutations(NAMES):
        # order[pos] — имя на позиции pos+1
        if not (order.index("Вера") + 1 == order.index("Глеб")):
            continue
        if not (order.index("Аня") > order.index("Борис")):
            continue
        if order.index("Дина") in (0, 4):
            continue
        if abs(order.index("Борис") - order.index("Вера")) != 2:
            continue
        if order.index("Глеб") == 1:
            continue
        solutions.append(order)
    return solutions


def _counting_gold():
    return sum(1 for n in range(1, 301) if (n % 3 == 0 or n % 5 == 0) and n % 7 != 0)


def _analytic_scores():
    weights = (0.4, 0.35, 0.25)
    ratings = {
        "Альфа": (6, 9, 4),
        "Бета": (8, 6, 7),
        "Гамма": (7, 7, 9),
    }
    return {
        name: sum(w * r for w, r in zip(weights, row)) for name, row in ratings.items()
    }


def verify_gold() -> None:
    """Проверяет эталоны кодом; падает с сообщением при расхождении."""
    # logic: ровно одно решение, третий человек == Вера
    solutions = _logic_solutions()
    if len(solutions) != 1:
        raise AssertionError(
            f"logic-01: ожидалось ровно 1 решение, найдено {len(solutions)}"
        )
    order = solutions[0]
    if order[2].lower() != TASKS[0].gold:
        raise AssertionError(
            f"logic-01: на третьей позиции {order[2]}, а gold={TASKS[0].gold!r}"
        )

    # counting: перебор 1..300
    if str(_counting_gold()) != TASKS[1].gold:
        raise AssertionError("counting-01: прямой перебор не сходится с gold")

    # analytic: взвешенные суммы, единственный максимум — Гамма
    scores = _analytic_scores()
    best = max(scores, key=scores.get)
    if list(scores.values()).count(max(scores.values())) != 1:
        raise AssertionError("analytic-01: максимум баллов не единственный")
    if best.lower() != TASKS[2].gold:
        raise AssertionError(
            f"analytic-01: лучший {best} ({scores[best]:.2f}), а gold={TASKS[2].gold!r}"
        )

    # политика утечки по семействам
    counting_task = TASKS[1]
    if counting_task.gold in counting_task.prompt:
        raise AssertionError("counting-01: эталонное число утекло в условие")

    logic_task, analytic_task = TASKS[0], TASKS[2]
    if len(logic_task.options or ()) < 5 or logic_task.gold not in (
        logic_task.options or ()
    ):
        raise AssertionError("logic-01: эталон не входит в набор из >= 5 вариантов")
    if len(analytic_task.options or ()) < 3 or analytic_task.gold not in (
        analytic_task.options or ()
    ):
        raise AssertionError("analytic-01: эталон не входит в набор из >= 3 вариантов")


if __name__ == "__main__":
    verify_gold()
    for t in TASKS:
        print(
            f"{t.id:12} family={t.family:9} gold={t.gold!r} baseline={t.baseline():.2f}"
        )
