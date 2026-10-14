"""Real MCP subprocess transport, discovery and call for each query."""
import asyncio
import json
import os
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from settings import DAY, CRM


async def crm_call(tool: str, arguments: dict | None = None):
    started = time.monotonic()
    # Do not give the read-only CRM child any provider credentials.
    env = {k: v for k, v in os.environ.items() if k.upper() in
           {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'LANG'}}
    env.update(DAY33_CRM_PATH=str(CRM), PYTHONIOENCODING='utf-8')
    params = StdioServerParameters(command=sys.executable,
        args=[str(DAY / 'crm_mcp_server.py')], env=env)
    async with asyncio.timeout(25):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                info = await client.initialize()
                catalog = await client.list_tools()
                if tool not in {t.name for t in catalog.tools}:
                    raise RuntimeError('MCP tool missing')
                result = await client.call_tool(tool, arguments=arguments or {})
                if result.is_error:
                    return {'demo': True, 'not_found': True}, {}
                payload = result.structured_content
                if payload is None:
                    payload = json.loads(next(b.text for b in result.content if b.type == 'text'))
                payload = payload.get('result', payload)
                if not isinstance(payload, dict) or payload.get('demo') is not True:
                    raise RuntimeError('Invalid CRM result')
                return payload, {'server': info.server_info.name,
                    'protocol_version': info.protocol_version,
                    'catalog': [t.name for t in catalog.tools], 'tool': tool,
                    'arguments': arguments or {},
                    'steps': ['initialize', 'tools/list', 'tools/call'],
                    'elapsed_ms': round((time.monotonic() - started) * 1000)}
