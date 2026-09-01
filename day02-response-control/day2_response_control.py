import argparse
import json
import os
import sys
import time
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API_KEY = os.environ.get("GEMINI_API_KEY")
# Цепочка fallback (по убыванию версий): если модель недоступна
# (429/503 после ретраев) — ВЕСЬ эксперимент (оба запроса) переезжает
# на следующую модель, чтобы baseline и controlled сравнивались
# на одной и той же модели.
MODEL_CHAIN = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
]
PRIMARY_MODEL = MODEL_CHAIN[0]
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = 60
MAX_RETRIES_PER_MODEL = 2
RETRY_WAIT_S = 10

BASE_PROMPT = (
    "Объясни, что такое RAG (Retrieval-Augmented Generation), как он работает, "
    "какие у него основные преимущества и ограничения и когда его стоит использовать."
)

REQUIRED_SECTIONS = [
    "ОПРЕДЕЛЕНИЕ:",
    "КАК РАБОТАЕТ:",
    "ПРЕИМУЩЕСТВА:",
    "ОГРАНИЧЕНИЯ:",
    "КОГДА ИСПОЛЬЗОВАТЬ:",
]

DEFAULT_WORD_LIMIT = 100
DEFAULT_STOP_SEQUENCE = "<END_RESPONSE>"
DEFAULT_MAX_OUTPUT_TOKENS = 256

BOX_WIDTH = 64

CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"


def build_system_instruction(word_limit, stop_sequence):
    return (
        "Ответь строго в формате:\n"
        "ОПРЕДЕЛЕНИЕ:\n"
        "<одно короткое объяснение>\n\n"
        "КАК РАБОТАЕТ:\n"
        "1. <шаг>\n"
        "2. <шаг>\n"
        "3. <шаг>\n\n"
        "ПРЕИМУЩЕСТВА:\n"
        "- <преимущество>\n\n"
        "ОГРАНИЧЕНИЯ:\n"
        "- <ограничение>\n\n"
        "КОГДА ИСПОЛЬЗОВАТЬ:\n"
        "<одно предложение>\n\n"
        f"Не более {word_limit} слов.\n"
        f"В самом конце выведи маркер {stop_sequence}."
    )


def build_generation_configs(stop_sequence, max_output_tokens):
    """Одинаковый thinkingConfig (thinkingLevel=low) для обоих запросов —
    A/B отличается только механизмами контроля ответа.
    Baseline: только thinkingConfig.
    Controlled: тот же thinkingConfig + maxOutputTokens + stopSequences."""
    shared = {"thinkingConfig": {"thinkingLevel": "low"}}
    base_config = dict(shared)
    controlled_config = {
        **shared,
        "maxOutputTokens": max_output_tokens,
        "stopSequences": [stop_sequence],
    }
    return base_config, controlled_config


class GeminiCallError(RuntimeError):
    """Обработаемая ошибка вызова (модель недоступна, сеть и т.п.)."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def call_gemini(model, prompt, generation_config, system_instruction=None):
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY не найден — проверь переменную окружения")
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": API_KEY,
    }
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    if generation_config:
        payload["generationConfig"] = generation_config
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    url = BASE_URL.format(model=model)
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise GeminiCallError(f"Ошибка сети: {e}") from None

    code = resp.status_code
    if code == 401 or code == 403:
        # Плохой/чужой ключ — ретраить и менять модель бессмысленно.
        raise RuntimeError(f"HTTP {code}: доступ запрещён (проверь GEMINI_API_KEY)")
    if code != 200:
        body = resp.text[:300]
        retryable = code in (429, 503)
        raise GeminiCallError(f"HTTP {code} ({'retryable' if retryable else 'fatal'}): {body}",
                              status_code=code)
    return resp.json()


def call_gemini_with_retries(model, prompt, generation_config, system_instruction=None, quiet=False):
    """До MAX_RETRIES_PER_MODEL попыток; 429/503 → пауза и повтор.
    Ошибки ключа (401/403) пробрасываются сразу."""
    last_error = None
    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        try:
            return call_gemini(model, prompt, generation_config, system_instruction)
        except GeminiCallError as e:
            last_error = e
            # 429/503 — ретраим; None (сеть/таймаут) — тоже, это транзиентно.
            if e.status_code is not None and e.status_code not in (429, 503):
                raise
            wait = RETRY_WAIT_S * attempt
            if not quiet:
                print(f"{YELLOW}  [{model}] HTTP {e.status_code}, жду {wait} сек... (попытка {attempt}/{MAX_RETRIES_PER_MODEL}){RESET}")
            time.sleep(wait)
    raise last_error


def extract_response(data):
    candidates = data.get("candidates") or []
    if not candidates:
        block_reason = data.get("promptFeedback", {}).get("blockReason")
        text = ""
        finish_reason = f"NO_CANDIDATES (blockReason={block_reason})" if block_reason else "NO_CANDIDATES"
    else:
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        finish_reason = candidate.get("finishReason")
    usage = data.get("usageMetadata", {})
    return {
        "text": text,
        "finish_reason": finish_reason,
        "output_tokens": usage.get("candidatesTokenCount"),
    }


def calculate_stats(text):
    return {
        "words": len(text.split()),
        "characters": len(text),
    }


def check_controlled(text, word_limit, stop_sequence):
    word_count = len(text.split())
    return {
        "sections_found": all(s in text for s in REQUIRED_SECTIONS),
        "word_count": word_count,
        "word_limit_ok": word_count <= word_limit,
        "marker_absent": stop_sequence not in text,
    }


def run_experiment(word_limit, stop_sequence, max_output_tokens, model_chain, quiet=False):
    """Ровно два запроса (baseline, controlled) с одинаковой структурой
    результата вне зависимости от значений ограничений или содержимого ответа.
    Формат/лимиты в controlled задаются системной инструкцией (systemInstruction),
    а не вклеиваются в пользовательский вопрос.

    Fallback на уровне эксперимента: обе части прогона выполняются на одной
    модели; если модель не смогла завершить оба запроса — весь A/B эксперимент
    запускается заново на следующей модели в model_chain (иначе baseline и
    controlled сравнивались бы на разных моделях)."""
    system_instruction = build_system_instruction(word_limit, stop_sequence)
    base_config, controlled_config = build_generation_configs(stop_sequence, max_output_tokens)

    attempts = []
    for model in model_chain:
        try:
            t_a = time.monotonic()
            data_a = call_gemini_with_retries(model, BASE_PROMPT, base_config, quiet=quiet)
            latency_a = time.monotonic() - t_a
            resp_a = extract_response(data_a)
            stats_a = calculate_stats(resp_a["text"])

            t_b = time.monotonic()
            data_b = call_gemini_with_retries(
                model, BASE_PROMPT, controlled_config,
                system_instruction=system_instruction, quiet=quiet,
            )
            latency_b = time.monotonic() - t_b
            resp_b = extract_response(data_b)
            stats_b = calculate_stats(resp_b["text"])
            checks_b = check_controlled(resp_b["text"], word_limit, stop_sequence)

            return {
                "model_used": model,
                "attempts": attempts + [{"model": model, "status": "ok"}],
                "system_instruction": system_instruction,
                "base_config": base_config,
                "controlled_config": controlled_config,
                "resp_a": resp_a,
                "stats_a": stats_a,
                "latency_a": latency_a,
                "resp_b": resp_b,
                "stats_b": stats_b,
                "latency_b": latency_b,
                "checks_b": checks_b,
            }
        except GeminiCallError as e:
            attempts.append({"model": model, "status": "failed", "error": str(e)[:200]})
            if not quiet:
                print(f"{YELLOW}  [{model}] недоступна: {e}{RESET}")
    err = GeminiCallError(
        f"Все модели в цепочке недоступны: {json.dumps(attempts, ensure_ascii=False)}"
    )
    err.attempts = attempts
    raise err


def truncate(text, max_len=90):
    text = text.strip()
    return text if len(text) <= max_len else text[:max_len].rstrip() + "..."


def pass_fail(ok):
    label = "PASS" if ok else "FAIL"
    color = GREEN if ok else RED
    return f"{color}[{label}]{RESET}"


def print_box(lines):
    top = "╔" + "═" * BOX_WIDTH + "╗"
    bottom = "╚" + "═" * BOX_WIDTH + "╝"
    print(top)
    for line in lines:
        print("║ " + line.ljust(BOX_WIDTH - 1) + "║")
    print(bottom)


def print_intro(word_limit, stop_sequence, max_output_tokens, model_chain):
    print()
    print(f"{BOLD}AI Advent Challenge — Day 02{RESET}")
    print("Response Control")
    print()
    if len(model_chain) == 1:
        print(f"Model: {model_chain[0]} (fallback отключён)")
    else:
        print(f"Model chain (fallback): {' -> '.join(model_chain)}")
    print()
    print("Experiment:")
    print("Same question -> two response strategies")
    print()
    print("[A] Baseline")
    print("    No format")
    print("    No length limit")
    print("    No stop sequence")
    print()
    print("[B] Controlled")
    print("    Explicit format")
    print(f"    <= {word_limit} words")
    print(f"    maxOutputTokens = {max_output_tokens}")
    print(f"    stopSequence = {stop_sequence}")


def print_base_question():
    print()
    print(f"{BOLD}BASE QUESTION{RESET}")
    print()
    print(BASE_PROMPT)


def print_diff_controls(word_limit, stop_sequence, max_output_tokens):
    print()
    print(f"{BOLD}What changes in request B?{RESET}")
    print()
    print("System instruction (systemInstruction):")
    print(f"  + explicit structure")
    print(f"  + <= {word_limit} words")
    print(f"  + end marker {stop_sequence}")
    print()
    print("API control:")
    print(f"  + maxOutputTokens = {max_output_tokens}")
    print(f"  + stopSequences = [\"{stop_sequence}\"]")
    print()
    print("Everything else stays the same.")


def wait_for_enter(prompt="Press Enter to run..."):
    try:
        input(f"\n{prompt}")
    except (EOFError, KeyboardInterrupt):
        print()


def print_result(label, title, subtitle, prompt, response, stats, system_instruction=None, latency=None):
    print()
    print_box([f"{label} — {title}", subtitle])
    print()
    print("Prompt:")
    print(truncate(prompt))
    if system_instruction:
        print()
        print("System instruction:")
        print(truncate(system_instruction, 200))
    print()
    print("Response:")
    print(response["text"].strip() or "(пустой ответ)")
    print()
    sep = "─" * (BOX_WIDTH + 2)
    print(sep)
    output_tokens = response["output_tokens"] if response["output_tokens"] is not None else "—"
    finish_reason = response["finish_reason"] if response["finish_reason"] is not None else "—"
    print(f"Words:         {stats['words']}")
    print(f"Characters:    {stats['characters']}")
    print(f"Output tokens: {output_tokens}")
    print(f"Finish reason: {finish_reason}")
    if latency is not None:
        print(f"Latency:       {latency:.1f}s")
    print(sep)


def print_checks(checks, word_limit):
    print()
    print("Controlled checks")
    sep = "─" * (BOX_WIDTH + 2)
    print(sep)
    print(f"{pass_fail(checks['sections_found'])} Required sections found")
    print(f"{pass_fail(checks['word_limit_ok'])} Word limit: {checks['word_count']} / {word_limit}")
    print(f"{pass_fail(checks['marker_absent'])} Stop marker not returned")
    print(sep)
    print("Note: finishReason=STOP alone does not prove the stop sequence fired —")
    print("it is also returned on normal completion.")


def print_comparison(word_limit, stop_sequence, max_output_tokens, stats_a, resp_a, stats_b, resp_b, checks):
    print()
    print_box(["FINAL COMPARISON".center(BOX_WIDTH - 1)])
    print()

    def row(label, a, b):
        print(f"{label:<24}{str(a):>18}{str(b):>18}")

    row("", "BASELINE", "CONTROLLED")
    print("─" * (BOX_WIDTH + 2))
    row("Explicit format", "No", "Yes")
    row("Word limit", "—", f"<={word_limit}")
    row("API token limit", "—", str(max_output_tokens))
    row("Stop sequence", "—", stop_sequence)
    print()
    tokens_a = resp_a["output_tokens"] if resp_a["output_tokens"] is not None else "—"
    tokens_b = resp_b["output_tokens"] if resp_b["output_tokens"] is not None else "—"
    row("Words", stats_a["words"], stats_b["words"])
    row("Characters", stats_a["characters"], stats_b["characters"])
    row("Output tokens", tokens_a, tokens_b)

    print()
    print_checks(checks, word_limit)

    print()
    print(f"{BOLD}RESULT:{RESET}")
    print(build_result_message(stats_a, stats_b, checks, resp_b, word_limit))


def build_result_message(stats_a, stats_b, checks, resp_b, word_limit):
    problems = []
    if not checks["sections_found"]:
        problems.append("controlled response is missing one or more required sections")
    if not checks["word_limit_ok"]:
        problems.append(f"controlled response exceeded the word limit ({checks['word_count']} / {word_limit} words)")
    if not checks["marker_absent"]:
        problems.append("the stop marker leaked into the returned text")
    if resp_b["finish_reason"] == "MAX_TOKENS":
        problems.append("controlled response was truncated by maxOutputTokens (finishReason=MAX_TOKENS)")

    if problems:
        lines = ["[WARNING] Controlled response did not fully satisfy the constraints:"]
        lines += [f"  - {p}" for p in problems]
        return "\n".join(lines)

    size_note = "shorter" if stats_b["words"] < stats_a["words"] else "not shorter"
    return (
        f"The same request produces a {size_note}, format-constrained and predictable "
        f"response ({stats_b['words']} vs {stats_a['words']} words) when output controls "
        "are applied via prompt instructions and generationConfig."
    )


def run_text_mode(word_limit, stop_sequence, max_output_tokens, interactive, model_chain):
    if not API_KEY:
        print(f"{RED}[ERROR]{RESET} GEMINI_API_KEY не найден в переменных окружения.")
        print("Задайте ключ перед запуском, например:")
        print("  export GEMINI_API_KEY=...       (bash)")
        print("  $env:GEMINI_API_KEY = \"...\"     (PowerShell)")
        sys.exit(1)

    print_intro(word_limit, stop_sequence, max_output_tokens, model_chain)
    if interactive:
        wait_for_enter()

    print_base_question()
    print_diff_controls(word_limit, stop_sequence, max_output_tokens)
    if interactive:
        wait_for_enter("Press Enter to run comparison...")

    try:
        result = run_experiment(word_limit, stop_sequence, max_output_tokens, model_chain)
    except RuntimeError as e:
        print(f"\n{RED}[ERROR]{RESET} Запрос не выполнен: {e}")
        sys.exit(1)

    failed = [a for a in result["attempts"] if a["status"] == "failed"]
    if failed:
        print()
        print(f"{YELLOW}[FALLBACK]{RESET} Использована модель: {result['model_used']}")
    print_result("A", "BASELINE", "No response control", BASE_PROMPT, result["resp_a"], result["stats_a"],
                 latency=result["latency_a"])
    print_result(
        "B", "CONTROLLED", "Format + Length + Stop",
        BASE_PROMPT, result["resp_b"], result["stats_b"],
        system_instruction=result["system_instruction"],
        latency=result["latency_b"],
    )
    print_comparison(
        word_limit, stop_sequence, max_output_tokens,
        result["stats_a"], result["resp_a"], result["stats_b"], result["resp_b"], result["checks_b"],
    )


def build_json_document(word_limit, stop_sequence, max_output_tokens, model_chain, result, error=None, attempts=None):
    """Собирает JSON-документ с фиксированной схемой: набор полей одинаков
    независимо от результата и даже при ошибке (result=None, error=...) —
    пустыми значениями заполняются ответные поля."""
    if result is None:
        base_config, controlled_config = build_generation_configs(stop_sequence, max_output_tokens)
        system_instruction = build_system_instruction(word_limit, stop_sequence)
        empty_resp = {"text": "", "finish_reason": None, "output_tokens": None}
        empty_stats = {"words": 0, "characters": 0}
        empty_checks = check_controlled("", word_limit, stop_sequence)
        model_used = None
        attempts = attempts or []
    else:
        base_config = result["base_config"]
        controlled_config = result["controlled_config"]
        system_instruction = result["system_instruction"]
        resp_a, resp_b = result["resp_a"], result["resp_b"]
        empty_resp = None
        model_used = result["model_used"]
        attempts = result["attempts"]

    output = {
        "model": PRIMARY_MODEL,
        "model_chain": model_chain,
        "model_used": model_used,
        "attempts": attempts,
        "base_prompt": BASE_PROMPT,
        "word_limit": word_limit,
        "stop_sequence": stop_sequence,
        "max_output_tokens": max_output_tokens,
        "error": error,
        "results": {
            "baseline": {
                "prompt": BASE_PROMPT,
                "generation_config": base_config,
                "text": (result["resp_a"]["text"] if result else empty_resp["text"]),
                "finish_reason": (result["resp_a"]["finish_reason"] if result else None),
                "output_tokens": (result["resp_a"]["output_tokens"] if result else None),
                "words": (result["stats_a"]["words"] if result else 0),
                "characters": (result["stats_a"]["characters"] if result else 0),
                "latency_seconds": (round(result["latency_a"], 2) if result else None),
            },
            "controlled": {
                "prompt": BASE_PROMPT,
                "system_instruction": system_instruction,
                "generation_config": controlled_config,
                "text": (result["resp_b"]["text"] if result else empty_resp["text"]),
                "finish_reason": (result["resp_b"]["finish_reason"] if result else None),
                "output_tokens": (result["resp_b"]["output_tokens"] if result else None),
                "words": (result["stats_b"]["words"] if result else 0),
                "characters": (result["stats_b"]["characters"] if result else 0),
                "latency_seconds": (round(result["latency_b"], 2) if result else None),
                "checks": (result["checks_b"] if result else empty_checks),
            },
        },
        "comparison": {
            "words": {
                "baseline": result["stats_a"]["words"] if result else 0,
                "controlled": result["stats_b"]["words"] if result else 0,
            },
            "characters": {
                "baseline": result["stats_a"]["characters"] if result else 0,
                "controlled": result["stats_b"]["characters"] if result else 0,
            },
            "output_tokens": {
                "baseline": result["resp_a"]["output_tokens"] if result else None,
                "controlled": result["resp_b"]["output_tokens"] if result else None,
            },
        },
    }
    return output


def run_json_mode(word_limit, stop_sequence, max_output_tokens, model_chain):
    """Печатает единственный JSON-документ с фиксированной схемой —
    структура полей одинакова независимо от результатов и ошибок."""
    if not API_KEY:
        doc = build_json_document(word_limit, stop_sequence, max_output_tokens, model_chain, None,
                                  error="GEMINI_API_KEY not set")
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        result = run_experiment(word_limit, stop_sequence, max_output_tokens, model_chain, quiet=True)
    except RuntimeError as e:
        doc = build_json_document(word_limit, stop_sequence, max_output_tokens, model_chain, None,
                                  error=str(e), attempts=getattr(e, "attempts", None))
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        sys.exit(1)

    doc = build_json_document(word_limit, stop_sequence, max_output_tokens, model_chain, result)
    print(json.dumps(doc, ensure_ascii=False, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description="Day 2 — Response Control: baseline vs controlled Gemini request")
    parser.add_argument("--mode", choices=["text", "json"], default="text",
                         help="text: демонстрационный вывод в терминал (по умолчанию); json: один детерминированный JSON-документ")
    parser.add_argument("--word-limit", type=int, default=DEFAULT_WORD_LIMIT,
                         help=f"лимит слов для controlled-ответа (по умолчанию {DEFAULT_WORD_LIMIT})")
    parser.add_argument("--stop-sequence", default=DEFAULT_STOP_SEQUENCE,
                         help=f"stop sequence / маркер конца ответа (по умолчанию {DEFAULT_STOP_SEQUENCE})")
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS,
                         help=f"maxOutputTokens для controlled-запроса (по умолчанию {DEFAULT_MAX_OUTPUT_TOKENS})")
    parser.add_argument("--no-interactive", action="store_true",
                         help="не ждать Enter между экранами в text-режиме (полезно для записи/автоматизации)")
    parser.add_argument("--model", default=None,
                        help=f"зафиксировать одну модель, отключить fallback (по умолчанию цепочка: {' -> '.join(MODEL_CHAIN)})")
    return parser.parse_args()


def main():
    args = parse_args()
    model_chain = [args.model] if args.model else MODEL_CHAIN
    if args.mode == "json":
        run_json_mode(args.word_limit, args.stop_sequence, args.max_output_tokens, model_chain)
    else:
        run_text_mode(args.word_limit, args.stop_sequence, args.max_output_tokens,
                      interactive=not args.no_interactive, model_chain=model_chain)


if __name__ == "__main__":
    main()
