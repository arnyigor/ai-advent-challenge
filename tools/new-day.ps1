param(
    [Parameter(Mandatory=$true)][int]$Day,
    [Parameter(Mandatory=$true)][string]$Slug,
    [Parameter(Mandatory=$true)][string]$Title
)

$d = "{0:D2}" -f $Day
$root = Split-Path -Parent $PSScriptRoot
$folder = Join-Path $root "day$d-$Slug"
New-Item -ItemType Directory -Path $folder -Force | Out-Null

$slugUnderscore = $Slug -replace '-', '_'
$entryFile = "day$d`_$slugUnderscore.py"

$readme = @"
# Day ${Day}: $Title

## Что делает

<!-- TODO: 1-2 предложения о задаче дня -->

## Стек

Python + tools/llm (общий транспорт Gemini/DeepSeek с ретраями, fallback по
цепочке моделей и опциональным стримингом — см. корневой README.md).

## Установка

``````bash
pip install -r requirements.txt
``````

## Настройка ключа

Ключ должен быть в переменной окружения ``GEMINI_API_KEY`` (не хранится в коде).

## Запуск

``````bash
python $entryFile --mode text
python $entryFile --mode json
``````

## Демо

Видео: <!-- TODO: вставить ссылку после submit-day.ps1 -->

## Структура

``````
day$d-$Slug/
├── $entryFile         # основной скрипт
├── requirements.txt   # зависимости
└── README.md
``````
"@

Set-Content -Path "$folder\README.md" -Value $readme -Encoding UTF8

@{ day = $Day; title = $Title; entrypoint = $entryFile } | ConvertTo-Json | Set-Content "$folder\challenge.json"

# Рабочий skeleton, а не пустой файл: bootstrap sys.path, model-chain fallback
# (tools/llm/runner.py), --mode text/json — тот же каркас, что в day02/day03.
# Тело эксперимента и вывод — TODO, специфика дня.
$pyTemplate = @'
"""Day __DAY__ — __TITLE__

TODO: 1-2 предложения о задаче дня.
"""

import argparse
import json
import sys
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
    GeminiCallError,
    calculate_stats,
    call_gemini_with_retries,
    extract_response,
    has_gemini_api_key,
)
from tools.llm.runner import run_with_model_fallback
from tools.llm.ui import BOLD, RED, RESET, YELLOW, print_box, wait_for_enter


def _retry_banner(message):
    print(f"{YELLOW}{message}{RESET}")


# TODO: замени на промпт задачи дня.
BASE_PROMPT = "TODO: сформулируй запрос к модели."


def run_experiment(model_chain, quiet=False):
    """Прогон на одной модели из цепочки; при retryable/model-unavailable
    ошибке (tools/llm/runner.py) пробует следующую модель в model_chain."""

    def _run_on_model(model):
        data = call_gemini_with_retries(
            model, BASE_PROMPT, quiet=quiet, retry_logger=_retry_banner
        )
        resp = extract_response(data)
        stats = calculate_stats(resp["text"])
        # TODO: добавь сюда специфичные для дня проверки/метрики.
        return {"resp": resp, "stats": stats}

    def _on_fallback(model, _next_model, e):
        if not quiet:
            print(f"{YELLOW}  [{model}] недоступна: {e}{RESET}")

    result, model_used, attempts = run_with_model_fallback(
        model_chain,
        _run_on_model,
        fallback_exc=GeminiCallError,
        on_fallback=_on_fallback,
        error_cls=GeminiCallError,
    )
    result["model_used"] = model_used
    result["attempts"] = attempts
    return result


def run_text_mode(model_chain, interactive):
    if not has_gemini_api_key():
        print(f"{RED}[ERROR]{RESET} GEMINI_API_KEY не найден в переменных окружения.")
        sys.exit(1)

    print()
    print_box([f"{BOLD}AI Advent Challenge — Day __DAY__{RESET}", "__TITLE__"])
    if interactive:
        wait_for_enter()

    try:
        result = run_experiment(model_chain)
    except RuntimeError as e:
        print(f"\n{RED}[ERROR]{RESET} Запрос не выполнен: {e}")
        sys.exit(1)

    failed = [a for a in result["attempts"] if a["status"] == "failed"]
    if failed:
        print(f"{YELLOW}[FALLBACK]{RESET} Использована модель: {result['model_used']}")

    # TODO: вывод результата для человека.
    print()
    print(result["resp"]["text"])


def build_json_document(model_chain, result=None, error=None, attempts=None):
    """Фиксированная схема JSON-документа — одинаковый набор полей при успехе
    и при ошибке (result=None), чтобы потребителю не пришлось ветвиться."""
    if result is None:
        model_used = None
        attempts = attempts or []
        text = ""
    else:
        model_used = result["model_used"]
        attempts = result["attempts"]
        text = result["resp"]["text"]

    return {
        "day": __DAY__,
        "model_chain": model_chain,
        "model_used": model_used,
        "attempts": attempts,
        "error": error,
        # TODO: расширь схему специфичными для дня полями.
        "result": {"text": text},
    }


def run_json_mode(model_chain):
    if not has_gemini_api_key():
        doc = build_json_document(model_chain, error="GEMINI_API_KEY not set")
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        result = run_experiment(model_chain, quiet=True)
    except RuntimeError as e:
        doc = build_json_document(
            model_chain, error=str(e), attempts=getattr(e, "attempts", None)
        )
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        sys.exit(1)

    doc = build_json_document(model_chain, result)
    print(json.dumps(doc, ensure_ascii=False, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description="Day __DAY__ — __TITLE__")
    parser.add_argument("--mode", choices=["text", "json"], default="text")
    parser.add_argument("--no-interactive", action="store_true")
    parser.add_argument(
        "--model",
        default=None,
        help=f"зафиксировать одну модель (по умолчанию цепочка: {' -> '.join(MODEL_CHAIN)})",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    model_chain = [args.model] if args.model else MODEL_CHAIN
    if args.mode == "json":
        run_json_mode(model_chain)
    else:
        run_text_mode(model_chain, interactive=not args.no_interactive)


if __name__ == "__main__":
    main()
'@

$pyContent = $pyTemplate.Replace('__DAY__', "$Day").Replace('__TITLE__', $Title)
Set-Content -Path "$folder\$entryFile" -Value $pyContent -Encoding UTF8

Set-Content -Path "$folder\requirements.txt" -Value "requests" -Encoding UTF8

Write-Host "Создано: $folder" -ForegroundColor Green
