"""Run three tools from one MCP server in one session."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER = Path(__file__).with_name("mcp_server.py")
DEFAULT_QUERY = "MCP"
NAMES = ("search", "summarize", "saveToFile")


def payload(result):
    if result.is_error:
        raise RuntimeError("; ".join(block.text for block in result.content if block.type == "text"))
    data = result.structured_content
    if data is None:
        blocks = [block.text for block in result.content if block.type == "text"]
        if len(blocks) != 1:
            raise RuntimeError("Неожиданный ответ MCP")
        data = json.loads(blocks[0])
    data = data.get("result", data)
    if not isinstance(data, dict):
        raise RuntimeError("Ответ MCP должен быть объектом")
    return data


async def run(query=DEFAULT_QUERY, *, server_path=SERVER, timeout=90):
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("Введите запрос длиной 1–200 символов")
    inherited = {key: os.environ[key] for key in ("DAY19_OUTPUT_DIR", "DAY19_SUMMARY_MODE", "DAY19_MODEL", "GEMINI_API_KEY") if key in os.environ}
    params = StdioServerParameters(command=sys.executable, args=[str(server_path)], env=inherited or None)
    async with asyncio.timeout(timeout):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                info = await session.initialize()
                catalog = await session.list_tools()
                tools = {tool.name: tool for tool in catalog.tools}
                if not all(name in tools for name in NAMES):
                    raise RuntimeError("Сервер не объявил все три инструмента")
                trace = []

                async def call(name, arguments):
                    result = payload(await session.call_tool(name, arguments=arguments))
                    trace.append({"tool": name, "arguments": arguments, "result": result})
                    return result

                found = await call("search", {"query": query})
                if not isinstance(found.get("run_id"), str) or found.get("query") != query or not isinstance(found.get("items"), list):
                    raise RuntimeError("Некорректный выход search")
                digest = await call("summarize", {"run_id": found["run_id"], "query": found["query"], "items": found["items"]})
                if digest.get("run_id") != found["run_id"] or digest.get("query") != query or not isinstance(digest.get("summary"), str) or not isinstance(digest.get("source_ids"), list) or digest.get("mode") not in ("model", "local"):
                    raise RuntimeError("Некорректный выход summarize")
                saved = await call("saveToFile", {"run_id": digest["run_id"], "query": digest["query"], "summary": digest["summary"], "source_ids": digest["source_ids"], "mode": digest["mode"], "model": digest["model"]})
                if saved.get("run_id") != found["run_id"] or not isinstance(saved.get("path"), str):
                    raise RuntimeError("Некорректный выход saveToFile")
                return {"server": info.server_info.name, "catalog": [{"name": tools[name].name, "description": tools[name].description, "inputSchema": tools[name].input_schema} for name in NAMES], "trace": trace, "file": saved["path"], "content": saved["content"]}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default=DEFAULT_QUERY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.query))
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for step in result["trace"]:
            print(f"{step['tool']}: {json.dumps(step['result'], ensure_ascii=False)}")
        print(f"Файл: {result['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
