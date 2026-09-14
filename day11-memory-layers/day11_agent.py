"""Interactive CLI for Day 11 memory layers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DAY_DIR.parent
for path in (ROOT_DIR, DAY_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent import MemoryAgent
from memory_store import LAYERS, MemoryStore
from providers import LiveProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="День 11 — три слоя памяти агента")
    parser.add_argument("--user", default="demo")
    parser.add_argument("--session", default="session-1")
    parser.add_argument("--task", default="task-1")
    parser.add_argument("--provider", choices=("auto", "deepseek", "gemini", "wormsoft"), default="auto")
    args = parser.parse_args()
    store = MemoryStore(DAY_DIR / "data")
    agent = MemoryAgent(store, LiveProvider(args.provider))
    user, session, task = args.user, args.session, args.task
    include = LAYERS
    print("День 11. /save <short|working|long> <ключ> = <значение>; /memory; /session <id>; /task <id>; /include <слои>; /exit")
    while True:
        try:
            line = input(f"\n[{user}/{session}/{task}] Вы> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line in {"/exit", "/quit"}:
            return 0
        if not line:
            continue
        try:
            if line == "/memory":
                print(store.snapshot(user_id=user, session_id=session, task_id=task))
            elif line.startswith("/session "):
                session = line.split(" ", 1)[1].strip()
                print(f"Сессия: {session}")
            elif line.startswith("/task "):
                task = line.split(" ", 1)[1].strip()
                print(f"Задача: {task}")
            elif line.startswith("/include "):
                include = tuple(x.strip() for x in line.split(" ", 1)[1].split(",") if x.strip())
                if any(x not in LAYERS for x in include):
                    raise ValueError("Допустимые слои: short, working, long")
                print(f"В контексте: {', '.join(include) or '(нет памяти)'}")
            elif line.startswith("/save "):
                spec = line[6:]
                left, sep, value = spec.partition("=")
                parts = left.strip().split(" ", 1)
                if not sep or len(parts) != 2:
                    raise ValueError("Формат: /save <слой> <ключ> = <значение>")
                store.save_fact(parts[0], user_id=user, session_id=session, task_id=task, key=parts[1], value=value)
                print(f"Сохранено в {parts[0]}: {parts[1].strip()}")
            else:
                result = agent.ask(user_id=user, session_id=session, task_id=task, user_text=line, include=include)
                print(f"Агент> {result['answer']}")
                used = result["context"]["memory_used"]
                print(f"Контекст: short={len(used['short']['messages'])} реплик, working={list(used['working'])}, long={list(used['long'])}")
        except (ValueError, RuntimeError) as exc:
            print(f"Ошибка: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
