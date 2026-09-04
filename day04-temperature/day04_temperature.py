"""Day 4 — Температура: один промпт, temperature в {0.0, 0.7, 1.2}, 3 повтора
каждое. Сравнение точности/креативности/разнообразия по self-similarity,
TTR, чеклисту фактов и деградациям (обрывы, срыв языка, повторы)."""

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

from tools.llm.deepseek import DEFAULT_MODEL as DEEPSEEK_DEFAULT_MODEL
from tools.llm.gemini import MODEL_CHAIN as GEMINI_MODEL_CHAIN
from tools.llm.ui import BOLD, GREEN, RED, RESET, YELLOW, print_box

from experiment import TEMPERATURES, run_experiment


def run_text_mode(model_chain, repeats, concurrency):
    print()
    print_box([f"{BOLD}AI Advent Challenge — Day 4{RESET}", "Температура"])

    def on_event(kind, payload):
        if kind == "preflight_passed":
            print(f"{GREEN}[OK]{RESET} preflight принят моделью {payload['model']}")
        elif kind == "sample_finished":
            s = payload
            print(
                f"  t={s['temperature']} r={s['repeat']}  "
                f"{s['words']} слов, {s['latency_ms']} мс, finish={s['finish_reason']}"
            )
        elif kind == "model_fallback":
            print(f"{YELLOW}[FALLBACK]{RESET} {payload['model']} -> {payload['next_model']}: {payload['error']}")

    try:
        doc = run_experiment(model_chain, repeats, concurrency, on_event=on_event)
    except RuntimeError as e:
        print(f"\n{RED}[ERROR]{RESET} Эксперимент не выполнен: {e}")
        sys.exit(1)

    print()
    print(f"Модель: {doc['model_spec']}  (prompt sha256={doc['locked']['prompt_sha256']})")
    print()
    for temperature in TEMPERATURES:
        m = doc["metrics"][str(temperature)]
        print(
            f"T={temperature:<4} self_similarity={m['self_similarity']:.2f}  "
            f"ttr={m['ttr']:.2f}  checklist={m['checklist_mean']:.1f}/5  "
            f"degradations={m['degradations']}  latency_mean={m['latency_ms_mean']:.0f}мс"
        )


def run_json_mode(model_chain, repeats, concurrency, out_path):
    try:
        doc = run_experiment(model_chain, repeats, concurrency)
    except RuntimeError as e:
        payload = {"error": str(e), "attempts": getattr(e, "attempts", None)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(1)

    doc["schema"] = "day4-temperature-v1"
    doc["temperatures"] = list(TEMPERATURES)
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    print(text)
    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Day 4 — Температура")
    parser.add_argument("--mode", choices=["text", "json"], default="text")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--model",
        default=None,
        help="зафиксировать одну модель, напр. deepseek:deepseek-v4-flash (по умолчанию deepseek-дефолт + gemini-цепочка fallback)",
    )
    parser.add_argument("--out", default=None, help="путь для сохранения JSON (только с --mode json)")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.model:
        model_chain = [args.model]
    else:
        model_chain = [f"deepseek:{DEEPSEEK_DEFAULT_MODEL}"] + list(GEMINI_MODEL_CHAIN)

    if args.mode == "json":
        run_json_mode(model_chain, args.repeats, args.concurrency, args.out)
    else:
        run_text_mode(model_chain, args.repeats, args.concurrency)


if __name__ == "__main__":
    main()
