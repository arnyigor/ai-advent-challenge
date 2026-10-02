"""Day 25: CLI chat — same ChatAgent as the web UI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from chat_agent import ChatAgent, DEFAULT_DATA_DIR, DEFAULT_MODEL


def print_state(state: dict) -> None:
    print(f"  Цель: {state['goal'] or '—'}")
    for label, key in (("Уточнения", "clarified"), ("Ограничения", "constraints"), ("Термины", "terms")):
        items = state[key]
        print(f"  {label}: " + ("; ".join(items) if items else "—"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--resume", help="session_id существующей сессии")
    args = parser.parse_args()
    agent = ChatAgent(model=args.model, data_dir=args.data_dir)
    if args.resume:
        session_id = args.resume
        agent.session(session_id)  # raises ValueError if unknown
        print(f"Возобновлена сессия {session_id}")
    else:
        session_id = agent.create_session()
        print(f"Новая сессия {session_id}")
    print("Команды: /state — память задачи, /exit — выход.")
    while True:
        try:
            message = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            continue
        if message == "/exit":
            break
        if message == "/state":
            print_state(agent.states.get(session_id).to_dict())
            continue
        result = agent.turn(session_id, message)
        print(f"Ассистент [{result['status']}]: {result['answer']}")
        for index, source in enumerate(result["sources"], 1):
            print(f"  И{index}: {source['source']} · {source['section']} · {source['chunk_id']}")
        if not result['sources']:
            print('  Источники: подтверждений не найдено.')
        for index, quote in enumerate(result["quotes"], 1):
            print(f"  Ц{index} (ход {quote['claim']}): {quote['quote']}")
        print_state(result["task_state"])
        if result['state_errors']:
            print('  Память не обновлена: сохранена предыдущая версия.')
    print(json.dumps({"session_id": session_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
