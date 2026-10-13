"""Read-only, fixed Git queries exposed through MCP stdio."""
import os
from pathlib import Path
import subprocess

from mcp.server import MCPServer

mcp = MCPServer('day31-project', version='1.0.0', log_level='WARNING')


@mcp.tool(description='Текущая ветка и HEAD проекта. Только чтение Git, без аргументов.')
def get_project_context() -> dict:
    root = Path(os.environ.get('DAY31_REPO_ROOT', Path(__file__).resolve().parents[1])).resolve()

    def git(*args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                encoding='utf-8', errors='replace', timeout=10)
        if result.returncode:
            raise RuntimeError('Git query failed; check repository root')
        return result.stdout.strip()

    branch = git('branch', '--show-current')
    return {'repository': Path(git('rev-parse', '--show-toplevel')).name,
            'branch': branch or '(detached HEAD)', 'head': git('rev-parse', 'HEAD'),
            'detached': not bool(branch)}


if __name__ == '__main__':
    mcp.run(transport='stdio')
