"""Метрики для эксперимента "температура".

Нормализация текста грубая (без pymorphy — лишняя зависимость): lowercase,
убрать пунктуацию/цифры, срезать русские окончания 1-3 символа у слов длиннее
5 букв. Огрубление одинаково бьёт по всем девяти ответам — сравнение честное.
"""

from __future__ import annotations

import re
from collections import Counter

STOPWORDS = frozenset(
    "и в во не что он на я с со как а то все она так его но да ты к у же вы за "
    "бы по только ее мне было вот от меня еще нет о из ему теперь когда даже ну "
    "вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там "
    "потом себя ничего ей может они тут где есть надо ней для мы тебя их чем "
    "была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того "
    "потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас "
    "были куда зачем всех никогда можно при наконец два об другой хоть после "
    "над больше тот через эти нас про всего них какая много разве три эту моя "
    "впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более "
    "всегда конечно всю между это".split()
)

_STRIP_RE = re.compile(r"[^\w\s]|\d", re.UNICODE)


def normalize_tokens(text: str) -> list[str]:
    text = _STRIP_RE.sub(" ", text.lower())
    tokens = []
    for word in text.split():
        if word in STOPWORDS:
            continue
        if len(word) > 5:
            word = word[:-3] if len(word) - 3 > 4 else word[:-1]
        tokens.append(word)
    return tokens


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def self_similarity(texts: list[str]) -> float:
    token_sets = [set(normalize_tokens(t)) for t in texts]
    pairs = [
        jaccard(token_sets[i], token_sets[j])
        for i in range(len(token_sets))
        for j in range(i + 1, len(token_sets))
    ]
    return sum(pairs) / len(pairs) if pairs else 1.0


def cross_similarity(texts_a: list[str], texts_b: list[str]) -> float:
    sets_a = [set(normalize_tokens(t)) for t in texts_a]
    sets_b = [set(normalize_tokens(t)) for t in texts_b]
    pairs = [jaccard(a, b) for a in sets_a for b in sets_b]
    return sum(pairs) / len(pairs) if pairs else 1.0


def type_token_ratio(text: str) -> float:
    tokens = normalize_tokens(text)
    return len(set(tokens)) / len(tokens) if tokens else 0.0


def length_cv(texts: list[str]) -> float:
    lengths = [len(t) for t in texts]
    n = len(lengths)
    if n < 2:
        return 0.0
    mean = sum(lengths) / n
    if mean == 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in lengths) / n
    return (variance ** 0.5) / mean


# Каждый концепт — набор alt-форм; присутствие любой засчитывает концепт.
# Проверка присутствия концепта, а не проверка истинности сказанного.
_CHECKLIST_PATTERNS = {
    "replays": ["переносит", "применяет заново", "поверх", "на новую баз", "переигрыва"],
    "rewrites_history": ["переписывает истори", "нов", "хеш", "меняет коммит", "перезаписыва"],
    "merge_contrast": ["merge", "мерж", "сохраня", "коммит слияния", "не переписыва"],
    "shared_risk": ["опубликован", "общ", "запушен", "force-push", "force push"],
    "use_case": ["локальн", "перед push", "актуализ", "линейн", "перед отправк"],
}


def check_facts(text: str) -> dict:
    lowered = text.lower()
    result = {}
    score = 0
    for key, alts in _CHECKLIST_PATTERNS.items():
        hit = any(alt in lowered for alt in alts)
        result[key] = hit
        score += int(hit)
    result["score"] = score
    return result


_SENTENCE_END_RE = re.compile(r"[.!?»\"']\s*$")
_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)


def detect_degradations(sample: dict) -> list[str]:
    issues = []
    text = sample.get("text", "")
    stripped = text.strip()

    if sample.get("finish_reason") == "MAX_TOKENS":
        issues.append("max_tokens")

    if stripped and not _SENTENCE_END_RE.search(stripped):
        issues.append("cut_off")

    letters = [c for c in stripped if c.isalpha()]
    if letters:
        cyrillic_ratio = len(_CYRILLIC_RE.findall(stripped)) / len(letters)
        if cyrillic_ratio < 0.6:
            issues.append("language_drift")

    words = stripped.split()
    if len(words) >= 15:
        ngrams = [" ".join(words[i:i + 5]) for i in range(len(words) - 4)]
        counts = Counter(ngrams)
        if any(c >= 3 for c in counts.values()):
            issues.append("repetition")

    return issues


def cross_similarity_matrix(samples: list[dict], temperatures: list[float]) -> dict:
    texts_by_temp = {}
    for sample in samples:
        texts_by_temp.setdefault(sample["temperature"], []).append(sample["text"])
    cross = {}
    for i, t_a in enumerate(temperatures):
        for t_b in temperatures[i + 1:]:
            key = f"{t_a}_vs_{t_b}"
            cross[key] = cross_similarity(texts_by_temp.get(t_a, []), texts_by_temp.get(t_b, []))
    return cross


def compute_verdict(metrics: dict) -> dict:
    """Градиент виден, если self_similarity монотонно убывает с ростом
    temperature и разброс между крайними точками заметен (>=0.10)."""
    ordered = sorted(metrics.items(), key=lambda kv: float(kv[0]))
    values = [m["self_similarity"] for _, m in ordered]
    monotonic = all(a >= b for a, b in zip(values, values[1:]))
    spread = values[0] - values[-1] if values else 0.0
    visible = monotonic and spread >= 0.10
    note = (
        f"self_similarity {values[0]:.2f} -> {values[-1]:.2f} "
        f"({'монотонно убывает' if monotonic else 'не монотонно'}, spread={spread:.2f})"
        if values
        else "нет данных"
    )
    return {"gradient_visible": visible, "note": note}


def summarize(samples: list[dict]) -> dict:
    by_temp: dict[float, list[dict]] = {}
    for sample in samples:
        by_temp.setdefault(sample["temperature"], []).append(sample)

    metrics = {}
    for temperature, group in by_temp.items():
        texts = [s["text"] for s in group]
        checklist_scores = [check_facts(t)["score"] for t in texts]
        degradations = [d for s in group for d in detect_degradations(s)]
        latencies = [s["latency_ms"] for s in group]
        metrics[str(temperature)] = {
            "self_similarity": self_similarity(texts),
            "ttr": sum(type_token_ratio(t) for t in texts) / len(texts),
            "len_cv": length_cv(texts),
            "checklist_mean": sum(checklist_scores) / len(checklist_scores),
            "degradations": len(degradations),
            "latency_ms_mean": sum(latencies) / len(latencies),
        }
    return metrics


def demo():
    same = ["привет мир тест", "привет мир тест", "привет мир тест"]
    diff = ["яблоко груша слива", "машина дорога город", "музыка звук тишина"]
    assert self_similarity(same) == 1.0
    assert self_similarity(diff) < 0.3
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0

    facts_hit = check_facts(
        "rebase переносит коммиты поверх новой базы и переписывает историю, "
        "в отличие от merge, который сохраняет историю и добавляет коммит слияния. "
        "риск в том, что опубликованную ветку менять нельзя (force-push). "
        "используй rebase для локальных веток перед push."
    )
    assert facts_hit["score"] == 5, facts_hit

    facts_empty = check_facts("это ответ ни о чём")
    assert facts_empty["score"] == 0

    assert detect_degradations({"text": "Обрыв без точки", "finish_reason": "MAX_TOKENS"}) == [
        "max_tokens",
        "cut_off",
    ]
    print("metrics.py: OK")


if __name__ == "__main__":
    demo()
