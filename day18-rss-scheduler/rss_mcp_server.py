"""Read-only MCP interface to the scheduled Habr digest."""

from mcp.server import MCPServer
from digest import latest_digest

mcp = MCPServer("day18-habr-digest", version="1.0.0", log_level="WARNING")


@mcp.tool(description="Вернуть последнюю сохранённую сводку Habr RSS и состояние фонового сборщика.")
def get_habr_digest() -> dict:
    return latest_digest()


if __name__ == "__main__":
    mcp.run(transport="stdio")
