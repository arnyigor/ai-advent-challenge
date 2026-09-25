"""Three separately registered MCP services; one process per role."""
import importlib.util
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

from mcp.server import MCPServer

DAY = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("day19_corpus", DAY.parent / "day19-mcp-composition" / "mcp_server.py")
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
CORPUS = previous.CORPUS


def summary_for(items):
    return "\n".join(f"[{item['id']}] {item['title']}: {item['text']}" for item in items)


def create_server(role):
    mcp = MCPServer(f"day20-{role}", version="1.0.0", log_level="WARNING")
    if role == "knowledge":
        @mcp.tool(description="Поиск ID материалов в локальном корпусе дней 16–18.")
        def search(query: str) -> dict:
            words = re.findall(r"\w+", query.casefold())
            return {"ids": [item["id"] for item in CORPUS if any(word in (item['title'] + ' ' + item['text']).casefold() for word in words)]}

        @mcp.tool(description="Прочитать исходный документ по ID из search.")
        def read(id: str) -> dict:
            for item in CORPUS:
                if item["id"] == id:
                    return dict(item)
            raise ValueError("Неизвестный документ")
    elif role == "analysis":
        @mcp.tool(description="Собрать локальную сводку с идентификаторами источников, без LLM.")
        def summarize(items: list[dict]) -> dict:
            if not items:
                raise ValueError("Нет материалов")
            return {"summary": summary_for(items), "source_ids": [item["id"] for item in items]}

        @mcp.tool(description="Проверить точное соответствие локальной сводки материалам корпуса и ID.")
        def verify(items: list[dict], summary: str, source_ids: list[str]) -> dict:
            valid = bool(items) and all(item in CORPUS for item in items)
            valid = valid and source_ids == [item["id"] for item in items] and summary == summary_for(items)
            return {"valid": valid, "checked_sources": len(items)}
    elif role == "storage":
        output = Path(os.environ.get("DAY20_OUTPUT_DIR", DAY / "output")).resolve()

        @mcp.tool(description="Сохранить проверенный отчёт в новый UTF-8 файл.")
        def save(content: str) -> dict:
            if not content.strip():
                raise ValueError("Пустой отчёт")
            output.mkdir(parents=True, exist_ok=True)
            id = uuid4().hex
            target = output / f"report-{id}.txt"
            with target.open("x", encoding="utf-8", newline="") as stream:
                stream.write(content)
            return {"id": id, "path": str(target)}

        @mcp.tool(description="Прочитать сохранённый отчёт для контроля записи.")
        def read(id: str) -> dict:
            if not re.fullmatch(r"[0-9a-f]{32}", id):
                raise ValueError("Некорректный ID отчёта")
            target = output / f"report-{id}.txt"
            return {"content": target.read_text(encoding="utf-8"), "path": str(target)}
    else:
        raise ValueError("Неизвестный сервер")
    return mcp


if __name__ == "__main__":
    create_server(sys.argv[1]).run(transport="stdio")
