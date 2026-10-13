"""MCP client: discover and invoke the project tool on every request."""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def get_context(root: Path) -> dict:
    env = dict(os.environ, DAY31_REPO_ROOT=str(root.resolve()), PYTHONIOENCODING='utf-8')
    parameters = StdioServerParameters(command=sys.executable,
        args=[str(Path(__file__).with_name('project_mcp_server.py'))], env=env)
    async with asyncio.timeout(30):
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                catalog = await session.list_tools()
                tool = next((t for t in catalog.tools if t.name == 'get_project_context'), None)
                if tool is None:
                    raise RuntimeError('MCP tool missing')
                result = await session.call_tool(tool.name, arguments={})
                if result.is_error:
                    raise RuntimeError('MCP Git query failed')
                payload = result.structured_content
                if payload is None:
                    blocks = [b.text for b in result.content if b.type == 'text']
                    if len(blocks) != 1:
                        raise RuntimeError('Invalid MCP content')
                    payload = json.loads(blocks[0])
                project = payload.get('result', payload)
                if (not isinstance(project, dict) or
                    not all(isinstance(project.get(k), str) and project[k] for k in ('repository', 'branch', 'head'))
                    or not isinstance(project.get('detached'), bool)):
                    raise RuntimeError('Invalid MCP project context')
                return {'project': project, 'mcp': {
                    'server': initialized.server_info.name,
                    'protocol_version': initialized.protocol_version,
                    'catalog': [{'name': t.name, 'description': t.description,
                                 'inputSchema': t.input_schema} for t in catalog.tools],
                    'tool': tool.name, 'arguments': {}, 'result': project,
                    'steps': ['initialize', 'tools/list', 'tools/call']}}
