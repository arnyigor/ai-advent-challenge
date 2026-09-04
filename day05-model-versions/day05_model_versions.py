"""CLI for Day 5 — model versions."""

from __future__ import annotations

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

from experiment import run_experiment
from tools.llm.ui import BOLD, GREEN, RESET, print_box


def parse_args():
    parser = argparse.ArgumentParser(description="Day 5 — сравнение версий моделей")
    parser.add_argument("--mode", choices=["text", "json"], default="text")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--local-url", default=None, help="URL локального OpenAI-compatible llama.cpp")
    parser.add_argument("--ollama-url", default=None, help="URL локального Ollama")
    parser.add_argument("--local-cpu-url", default=None, help="URL локального CPU llama.cpp")
    parser.add_argument("--no-local", action="store_true", help="не запускать локальную модель")
    parser.add_argument("--no-local-small", action="store_true", help="не запускать локальную Qwen3.5 4B")
    parser.add_argument("--no-local-cpu", action="store_true", help="не запускать локальную Qwen3 1.7B CPU")
    parser.add_argument("--no-api-controls", action="store_true", help="не запускать Gemini и DeepSeek")
    parser.add_argument("--no-hf", action="store_true", help="не запускать модели Hugging Face")
    parser.add_argument("--local-only", action="store_true", help="запустить только локальную модель")
    parser.add_argument("--out", default=None, help="сохранить итоговый JSON")
    return parser.parse_args()


def main():
    args = parse_args()
    print_box([f"{BOLD}AI Advent Challenge — Day 5{RESET}", "Версии моделей"])

    def on_event(kind, data):
        if args.mode != "text":
            return
        if kind == "model_started":
            print(f"\n{BOLD}{data['label']}{RESET}")
        elif kind == "sample_finished":
            evaluation = data["evaluation"]
            cost = data["cost_usd"]
            cost_label = "$0 (local)" if data["backend"] == "local" else (f"${cost:.6f}" if cost is not None else "н/д")
            print(
                f"  прогон {data['repeat']}: {data['latency_ms']} мс · "
                f"{data['output_tokens'] or '?'} токенов · тесты "
                f"{evaluation['passed']}/{evaluation['total']} · {cost_label}"
            )

    doc = run_experiment(
        repeats=args.repeats,
        local_url=args.local_url,
        ollama_url=args.ollama_url,
        local_cpu_url=args.local_cpu_url,
        include_local=not args.no_local,
        include_local_small=not args.no_local_small,
        include_local_cpu=not args.no_local_cpu,
        include_hf=not args.local_only and not args.no_hf,
        include_api=not args.local_only and not args.no_api_controls,
        on_event=on_event,
    )
    if args.mode == "json":
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(f"\n{GREEN}Вывод:{RESET} {doc['verdict']}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
