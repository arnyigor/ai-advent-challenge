"""One stdio MCP server with three composable tools."""

import os
from pathlib import Path
from uuid import uuid4
import sys

from mcp.server import MCPServer


mcp = MCPServer("day19-composition", version="1.0.0", log_level="WARNING")
CORPUS = [
    {"id": "d16", "title": "День 16: подключение MCP", "text": "Клиент устанавливает соединение, выполняет initialize и получает каталог инструментов через tools/list.", "source": "day16-mcp-connection"},
    {"id": "d17", "title": "День 17: первый MCP-инструмент", "text": "Локальный MCP-сервер объявляет инструмент get_git_snapshot. Клиент вызывает его через tools/call и использует результат.", "source": "day17-first-mcp-tool"},
    {"id": "d18", "title": "День 18: RSS и MCP", "text": "Сборщик сохраняет RSS-материалы, а MCP-инструмент get_habr_digest отдаёт последнюю сводку.", "source": "day18-rss-scheduler"},
]
OUTPUT_DIR = Path(os.environ.get("DAY19_OUTPUT_DIR", Path(__file__).resolve().parent / "output")).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "day18-rss-scheduler"))
from day18_providers import GEMINI_MODELS, generate

MODEL = os.environ.get("DAY19_MODEL", GEMINI_MODELS[1])


@mcp.tool(description="Найти материалы во встроенном корпусе дней 16–18. Возвращает элементы с идентификаторами и источниками.")
def search(query: str) -> dict:
    words = [word.casefold() for word in query.strip().split() if word.strip()]
    if not words or len(query) > 200:
        raise ValueError("query должен содержать 1–200 символов")
    items = [item for item in CORPUS if any(word in (item["title"] + " " + item["text"] + " " + item["source"]).casefold() for word in words)]
    return {"run_id": uuid4().hex, "query": query, "items": items}


@mcp.tool(description="Составить сводку по результатам search с помощью Gemini; при отсутствии ключа использовать явно обозначенный локальный режим.")
def summarize(run_id: str, query: str, items: list[dict]) -> dict:
    if not run_id or not query or not isinstance(items, list):
        raise ValueError("Некорректный результат поиска")
    for item in items:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("id", "title", "text", "source")):
            raise ValueError("Некорректный элемент поиска")
    plain = "\n".join(f"• {item['title']}: {item['text']}" for item in items) if items else "По запросу ничего не найдено."
    mode, model, summary, note = "local", None, plain, "Локальная сводка без модели"
    if items and os.environ.get("DAY19_SUMMARY_MODE") != "plain" and os.environ.get("GEMINI_API_KEY"):
        if MODEL not in GEMINI_MODELS:
            raise ValueError("DAY19_MODEL должен быть одной из разрешённых моделей Gemini")
        prompt = ("Составь короткую связную сводку на русском по запросу: " + query + ". "
                  "Используй только материалы ниже, не добавляй фактов. Укажи дни и их роль. "
                  "Ответ 3–5 предложений, без Markdown.\n\n" + plain)
        try:
            generated, actual_model = generate(MODEL, prompt)
            if not generated.strip():
                raise ValueError("Пустой ответ модели")
            mode, model, summary, note = "model", actual_model, generated.strip(), "Сводка получена от Gemini"
        except Exception as exc:
            note = f"Модель недоступна ({type(exc).__name__}); использована локальная сводка"
    return {"run_id": run_id, "query": query, "summary": summary, "source_ids": [item["id"] for item in items], "source_count": len(items), "mode": mode, "model": model, "note": note}


@mcp.tool(description="Сохранить сводку в новый UTF-8 файл выделенного каталога дня 19.")
def saveToFile(run_id: str, query: str, summary: str, source_ids: list[str], mode: str, model: str | None) -> dict:
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("Некорректный run_id")
    if not query or not summary or not isinstance(source_ids, list) or not all(isinstance(x, str) for x in source_ids):
        raise ValueError("Некорректные данные сводки")
    if mode not in ("model", "local") or (mode == "model" and not model):
        raise ValueError("Некорректный режим сводки")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"digest-{run_id}.txt"
    content = f"Запрос: {query}\nРежим: {mode}\nМодель: {model or 'не использовалась'}\nИсточники: {', '.join(source_ids) or 'нет'}\n\n{summary}\n"
    with target.open("x", encoding="utf-8") as stream:
        stream.write(content)
    return {"run_id": run_id, "path": str(target), "bytes_written": len(content.encode("utf-8")), "content": content}


if __name__ == "__main__":
    mcp.run(transport="stdio")
