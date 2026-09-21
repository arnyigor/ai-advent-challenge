"""Connect to a local MCP server and discover its tools without calling them."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams

DEFAULT_SERVER = Path(__file__).with_name("demo_server.py")


async def discover(server_path: Path = DEFAULT_SERVER, timeout: float = 30,
                   *, command: list[str] | None = None, url: str | None = None,
                   on_event=None) -> dict:
    """Perform a real handshake and retrieve every page of tools."""
    def emit(stage, message):
        if on_event is not None:
            on_event(stage, message)

    emit("starting", "Запускаем соединение с MCP-сервером")
    if url:
        connection = streamable_http_client(url)
    else:
        if not command:
            command = [sys.executable, str(Path(server_path).resolve(strict=True))]
        params = StdioServerParameters(command=command[0], args=command[1:])
        connection = stdio_client(params)
    async with asyncio.timeout(timeout):
        async with connection as streams:
            read, write = streams[:2]
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                emit("initialized", f"Сервер {initialized.server_info.name} подтвердил соединение")
                tools, seen_cursors = [], set()
                cursor = None
                while True:
                    page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
                    tools.extend(
                        tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for tool in page.tools
                    )
                    cursor = page.next_cursor
                    if cursor is None:
                        break
                    if cursor in seen_cursors:
                        raise RuntimeError("Server repeated a tools/list cursor")
                    seen_cursors.add(cursor)
                emit("listed", f"Инструментов в полученном каталоге: {len(tools)}")
    emit("closed", "Сессия закрыта. Каталог доступен для просмотра")
    return {
        "handshake": "ok",
        "transport": "streamable-http" if url else "stdio",
        "protocolVersion": initialized.protocol_version,
        "server": initialized.server_info.model_dump(mode="json", by_alias=True, exclude_none=True),
        "tools": tools,
        "sessionClosed": True,
    }


def error_message(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(error_message(child) for child in exc.exceptions)
    return str(exc) or type(exc).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--server", type=Path, default=DEFAULT_SERVER)
    target.add_argument("--url", help="Existing Streamable HTTP MCP endpoint")
    target.add_argument("--command", nargs=argparse.REMAINDER,
                        help="Existing stdio server command and arguments (last option)")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--json", action="store_true", help="Print the discovery result as JSON")
    args = parser.parse_args()
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be a finite positive number")
    if args.command == []:
        parser.error("--command needs a program to launch")
    try:
        result = asyncio.run(discover(args.server, args.timeout, command=args.command, url=args.url))
    except Exception as exc:
        print(f"MCP connection failed: {error_message(exc)}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        print(f"MCP handshake: OK ({result['transport']})")
        print(f"Server: {result['server']['name']} {result['server']['version']}")
        print(f"Protocol: {result['protocolVersion']}")
        print(f"Available tools: {len(result['tools'])}")
        for tool in result["tools"]:
            print(f"\n- {tool['name']}: {tool.get('description', '')}")
            print("  inputSchema: " + json.dumps(tool["inputSchema"], sort_keys=True))
        print("\nMCP session closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
