"""Gemini selects tools; this client routes them across three real MCP sessions."""
import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys

from jsonschema import validate
from gemini_agent import GeminiAgent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DAY = Path(__file__).resolve().parent
DEFAULT_QUERY = "MCP"


def payload(result):
    if result.is_error:
        raise RuntimeError("; ".join(block.text for block in result.content if block.type == "text"))
    data = result.structured_content
    if data is None:
        data = json.loads(next(block.text for block in result.content if block.type == "text"))
    data = data.get("result", data)
    if not isinstance(data, dict):
        raise RuntimeError("MCP ответ должен быть объектом")
    return data


class Router:
    def __init__(self):
        self.routes = {}
        self.catalog = []
        self.trace = []

    async def connect(self, stack, registry):
        for name, config in registry.items():
            env = {"PYTHONUTF8": "1"}
            if "DAY20_OUTPUT_DIR" in os.environ:
                env["DAY20_OUTPUT_DIR"] = os.environ["DAY20_OUTPUT_DIR"]
            params = StdioServerParameters(command=sys.executable, args=[str(DAY / config["script"]), *config["args"]], env=env)
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            info = await session.initialize()
            if info.server_info.name != f"day20-{name}":
                raise RuntimeError("Имя сервера не соответствует регистрации")
            catalog = await session.list_tools()
            for tool in catalog.tools:
                route = f"{name}.{tool.name}"
                if route in self.routes:
                    raise RuntimeError("Повтор маршрута")
                self.routes[route] = (session, tool)
                self.catalog.append({"name": route, "server": name, "description": tool.description, "inputSchema": tool.input_schema})

    async def call(self, route, arguments, reason):
        if route not in self.routes:
            raise ValueError(f"Неизвестный маршрут: {route}")
        session, tool = self.routes[route]
        validate(arguments, tool.input_schema)
        if route == "storage.save":
            verified = [step for step in self.trace if step["tool"] == "analysis.verify" and step["result"].get("valid")]
            digests = [step for step in self.trace if step["tool"] == "analysis.summarize"]
            if not verified or not digests or arguments["content"] != digests[-1]["result"]["summary"]:
                raise RuntimeError("Сохранение разрешено только для проверенной сводки")
        step = {"server": route.split('.')[0], "tool": route, "reason": reason, "arguments": arguments}
        self.trace.append(step)
        try:
            step["result"] = payload(await session.call_tool(tool.name, arguments=arguments))
        except Exception:
            step["error"] = "Вызов MCP завершился ошибкой"
            raise
        return step["result"]


async def run(query=DEFAULT_QUERY, *, timeout=600, max_steps=16, agent=None):
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("Введите запрос длиной 1–200 символов")
    model_agent = agent or GeminiAgent()
    model_agent.history = [{"role": "user", "parts": [{"text": query}]}]
    router = Router()
    registry = json.loads((DAY / "servers.json").read_text(encoding="utf-8"))
    async with asyncio.timeout(timeout):
        async with AsyncExitStack() as stack:
            await router.connect(stack, registry)
            for _ in range(max_steps + 1):
                decision = await model_agent.next(router.catalog)
                if "answer" in decision:
                    break
                if len(router.trace) >= max_steps:
                    raise RuntimeError("Превышен лимит шагов")
                result = await router.call(decision["tool"], decision["arguments"], "Инструмент выбран моделью")
                model_agent.observe(decision, result)
            else:
                raise RuntimeError("Модель не завершила задачу")
    results = {step["tool"]: step["result"] for step in router.trace}
    saved = results.get("storage.read", {})
    digest = results.get("analysis.summarize", {})
    if "storage.save" in results:
        if not saved or saved["content"] != digest.get("summary"):
            raise RuntimeError("Записанный отчёт не был проверен чтением")
    if digest and not results.get("analysis.verify", {}).get("valid"):
        raise RuntimeError("Сводка не прошла проверку")
    return {"agent": "Gemini function calling", "model": model_agent.model,
            "model_turns": model_agent.turns, "model_answer": decision["answer"],
            "servers": list(registry), "catalog": router.catalog, "trace": router.trace,
            "file": saved.get("path"), "content": saved.get("content", digest.get("summary", "Ничего не найдено")),
            "verified": "storage.read" in results}


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
        print(f"Agent failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for step in result["trace"]:
            print(f"{step['tool']}: {step['reason']}")
        print(f"Модель: {result['model']}; ходов: {result['model_turns']}")
        print(result["model_answer"])
        print(result["content"])
        print(f"Файл: {result['file']}; проверен: {result['verified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
