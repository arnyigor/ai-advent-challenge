"""Общий паттерн "модель за моделью, пока одна не сработает" — было
продублировано в day2 (run_experiment) и day3 (run_with_fallback) почти
дословно: цикл по model_chain, накопление attempts, исключение с деталями
всех попыток, если ни одна модель не сработала.

Печать/логирование фолбэка намеренно не входит сюда — оно у каждого дня своё
(цвета, event-репортер и т.д.); on_fallback-колбэк остаётся точкой расширения.
"""

import json


def run_with_model_fallback(model_chain, work_fn, *, fallback_exc, on_fallback=None, error_cls=RuntimeError):
    """Пробует work_fn(model) по цепочке моделей по порядку.

    fallback_exc: исключение(я), при которых стоит перейти к следующей модели
        (retryable/model-unavailable). Любое другое исключение из work_fn
        всплывает немедленно — цепочка не продолжается.
    on_fallback(model, next_model, error): опциональный колбэк на каждый
        неудачный переход (next_model=None на последней модели в цепочке).

    Возвращает (result, model_used, attempts). attempts — список
    {"model", "status": "ok"|"failed", ["error"]} в порядке попыток.
    Если ни одна модель не сработала — поднимает error_cls с attempts в
    JSON-сообщении и в атрибуте .attempts (для JSON-режима дня).
    """
    attempts = []
    for index, model in enumerate(model_chain):
        try:
            result = work_fn(model)
            attempts.append({"model": model, "status": "ok"})
            return result, model, attempts
        except fallback_exc as e:
            attempts.append({"model": model, "status": "failed", "error": str(e)[:200]})
            if on_fallback:
                next_model = model_chain[index + 1] if index + 1 < len(model_chain) else None
                on_fallback(model, next_model, e)
    err = error_cls(f"Все модели в цепочке недоступны: {json.dumps(attempts, ensure_ascii=False)}")
    err.attempts = attempts
    raise err
