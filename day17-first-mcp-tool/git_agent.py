"""Small deterministic agent that discovers and calls the Day 17 MCP tool."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER = Path(__file__).with_name("git_mcp_server.py")
QUESTIONS = {
    "summary": "Что сейчас с Git-репозиторием?",
    "latest_commit": "Какой последний коммит?",
}


def answer(snapshot: dict) -> str:
    if snapshot["scope"] == "summary":
        changes = snapshot["tracked_changes"]
        condition = "отслеживаемые файлы чистые" if snapshot["clean_tracked_files"] else f"изменённых отслеживаемых файлов: {changes}"
        return f"Репозиторий {snapshot['repository']}, ветка {snapshot['branch']}; {condition}."
    return (f"Последний коммит в {snapshot['repository']}: {snapshot['short_hash']} — "
            f"{snapshot['subject']}. Автор: {snapshot['author']}; дата: {snapshot['date']}.")


async def ask(scope: str, *, server_path: Path = SERVER, timeout: float = 30) -> dict:
    if scope not in QUESTIONS:
        raise ValueError("Доступны запросы summary и latest_commit")
    parameters = StdioServerParameters(command=sys.executable, args=[str(server_path)])
    async with asyncio.timeout(timeout):
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                catalog = await session.list_tools()
                tool = next((item for item in catalog.tools if item.name == "get_git_snapshot"), None)
                if tool is None:
                    raise RuntimeError("MCP-сервер не объявил get_git_snapshot")
                arguments = {"scope": scope}
                result = await session.call_tool(tool.name, arguments=arguments)
                if result.is_error:
                    raise RuntimeError("MCP tool error: " + " ".join(
                        block.text for block in result.content if block.type == "text"))
                payload = result.structured_content
                if payload is None:
                    text_blocks = [block.text for block in result.content if block.type == "text"]
                    if len(text_blocks) != 1:
                        raise RuntimeError("Unexpected MCP tool result")
                    payload = json.loads(text_blocks[0])
                snapshot = payload.get("result", payload)
                if not isinstance(snapshot, dict) or snapshot.get("scope") != scope:
                    raise RuntimeError("Unexpected MCP tool payload")
                return {
                    "question": QUESTIONS[scope], "server": initialized.server_info.name,
                    "tool": tool.name, "description": tool.description,
                    "inputSchema": tool.input_schema, "arguments": arguments,
                    "result": snapshot, "answer": answer(snapshot),
                    "steps": ["initialize", "tools/list", "tools/call", "ответ агента"],
                }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", nargs="?", choices=tuple(QUESTIONS), default="summary")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(ask(args.scope))
    except Exception as exc:
        print(f"MCP call failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Вопрос: {result['question']}")
        print(f"MCP: {result['server']} → {result['tool']}({json.dumps(result['arguments'])})")
        print("Результат: " + json.dumps(result["result"], ensure_ascii=False))
        print("Агент: " + result["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
