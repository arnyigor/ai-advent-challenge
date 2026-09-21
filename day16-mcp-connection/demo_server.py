"""Local MCP server. stdout is reserved for protocol messages."""

from mcp.server import MCPServer

mcp = MCPServer("day16-demo", version="1.0.0", log_level="WARNING")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool()
def greet(name: str) -> str:
    """Return a greeting for the supplied name."""
    return f"Hello, {name}!"


if __name__ == "__main__":
    mcp.run(transport="stdio")
