"""MCP stdio-сессия на весь прогон агента: каталог инструментов + вызовы."""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).with_name('files_mcp_server.py')


class FileToolSession:
    """Один MCP-процесс на прогон: initialize → tools/list → N × tools/call."""

    def __init__(self, project_root=None, baseline_root=None, timeout=60):
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        if project_root is not None:
            env['DAY34_PROJECT_ROOT'] = str(Path(project_root).resolve())
        if baseline_root is not None:
            env['DAY34_BASELINE_ROOT'] = str(Path(baseline_root).resolve())
        self.parameters = StdioServerParameters(command=sys.executable,
                                                args=[str(SERVER)], env=env)
        self.timeout = timeout
        self._stack = None
        self.session = None
        self.server_name = None
        self.protocol_version = None
        self.catalog = []

    async def __aenter__(self):
        # Без asyncio.timeout вокруг: anyio требует выхода из cancel scope
        # в том же порядке/задаче, а закрытие происходит позже в __aexit__.
        self._stack = stdio_client(self.parameters)
        read, write = await self._stack.__aenter__()
        self.session = await ClientSession(read, write).__aenter__()
        initialized = await self.session.initialize()
        self.server_name = initialized.server_info.name
        self.protocol_version = initialized.protocol_version
        catalog = await self.session.list_tools()
        self.catalog = [{'name': t.name, 'description': t.description,
                         'inputSchema': t.input_schema} for t in catalog.tools]
        return self

    async def __aexit__(self, *exc):
        # anyio task group внутри stdio_client падает ("cancel scope in a different
        # task"), если закрывать контекст с проброшенным исключением. Закрываем
        # чисто, ошибки очистки гасим; исходное исключение не подавляем (return False).
        if self.session is not None:
            try:
                await self.session.__aexit__(None, None, None)
            except BaseException:
                pass
        if self._stack is not None:
            try:
                await self._stack.__aexit__(None, None, None)
            except BaseException:
                pass
        return False

    async def call(self, name: str, arguments: dict) -> dict:
        if self.session is None:
            raise RuntimeError('MCP-сессия не открыта')
        if name not in {t['name'] for t in self.catalog}:
            raise ValueError(f'неизвестный инструмент: {name}')
        if not isinstance(arguments, dict):
            raise ValueError('arguments: ожидается объект')
        async with asyncio.timeout(self.timeout):
            result = await self.session.call_tool(name, arguments=arguments)
        if result.is_error:
            blocks = [b.text for b in result.content if b.type == 'text']
            raise RuntimeError('MCP tool error: ' + (blocks[0][:500] if blocks else name))
        payload = result.structured_content
        if payload is None:
            blocks = [b.text for b in result.content if b.type == 'text']
            if len(blocks) != 1:
                raise RuntimeError('MCP: невалидный ответ инструмента')
            payload = json.loads(blocks[0])
        if isinstance(payload, dict) and 'result' in payload and len(payload) == 1:
            payload = payload['result']
        if not isinstance(payload, dict):
            raise RuntimeError('MCP: инструмент вернул не объект')
        return payload
