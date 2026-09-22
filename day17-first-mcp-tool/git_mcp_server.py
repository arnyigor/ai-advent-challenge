"""Read-only Git API exposed as a local MCP tool over stdio."""

import os
from pathlib import Path
import subprocess
from typing import Literal

from mcp.server import MCPServer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
mcp = MCPServer("day17-git", version="1.0.0", log_level="WARNING")


def git(*arguments: str) -> str:
    root = Path(os.environ.get("DAY17_REPO_ROOT", PROJECT_ROOT)).resolve()
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=10, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


@mcp.tool(description="Прочитать сводку Git или последний коммит текущего репозитория. Только чтение.")
def get_git_snapshot(scope: Literal["summary", "latest_commit"]) -> dict:
    """Return a Git snapshot. scope: summary for branch/change counts, latest_commit for commit details."""
    repository = Path(git("rev-parse", "--show-toplevel")).name
    if scope == "summary":
        lines = git("status", "--porcelain=v1", "--untracked-files=no").splitlines()
        return {
            "scope": scope, "repository": repository,
            "branch": git("branch", "--show-current") or "(detached HEAD)",
            "tracked_changes": len(lines),
            "clean_tracked_files": not lines,
        }
    commit = git("log", "-1", "--format=%H%x00%h%x00%s%x00%an%x00%aI").split("\x00")
    if len(commit) != 5:
        raise RuntimeError("Unexpected Git log response")
    return {
        "scope": scope, "repository": repository, "hash": commit[0],
        "short_hash": commit[1], "subject": commit[2],
        "author": commit[3], "date": commit[4],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
