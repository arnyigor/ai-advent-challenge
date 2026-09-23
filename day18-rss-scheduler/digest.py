"""Build and persist an RSS digest, with a plain-text fallback."""

from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import os

from feed_store import DB_PATH, connect, recent_articles, status
from day18_providers import fallback, generate


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def excerpt(raw):
    parser = _Text()
    parser.feed(raw or "")
    return " ".join(unescape(" ".join(parser.parts)).split())[:380]


def plain_digest(articles):
    groups = {
        "Модели и инструменты": ("модел", "qwen", "gemini", "нейросет", "llm"),
        "Агенты и автоматизация": ("агент", "rag", "автоматизац", "поиск"),
        "Безопасность и применение": ("безопас", "доступ", "прав", "бизнес", "работ"),
    }
    counts = {name: 0 for name in groups}
    for item in articles:
        title = item["title"].lower()
        for name, words in groups.items():
            if any(word in title for word in words):
                counts[name] += 1
    themes = "; ".join(f"{name.lower()} — {count}" for name, count in counts.items() if count)
    lines = [f"Обзор Habr: {len(articles)} новых публикаций об ИИ.", "", "Темы выпуска", themes or "Темы разнообразны; ниже приведены заголовки и выдержки из RSS.", "", "Материалы"]
    for number, item in enumerate(articles, 1):
        note = excerpt(item["description"])
        lines.extend([f"{number}. {item['title']}", note or "В RSS есть только заголовок: подробности доступны по ссылке.", item["url"], ""])
    lines.extend(["Что читать сначала", "Начните с первых материалов списка и откройте полные публикации по ссылкам. Эта сводка составлена только из RSS, поэтому детали статей здесь не проверялись."])
    return "\n".join(lines)


def build_digest(*, db_path=DB_PATH, call=None):
    db = connect(db_path)
    try:
        previous = db.execute("SELECT created_at FROM digests ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        db.close()
    articles = recent_articles(db_path, limit=10, since=previous[0] if previous else None)
    if not articles:
        raise ValueError("No new articles since the previous digest")
    lines = [f"{number}. {item['title']}\nОписание RSS: {excerpt(item['description'])}\nСсылка: {item['url']}" for number, item in enumerate(articles, 1)]
    plain = plain_digest(articles)
    prompt = ("Подготовь содержательную ежедневную сводку на русском объёмом 350–500 слов. "
              "Структура: 1) главные темы дня (3–5 предложений); 2) 5–7 публикаций, для каждой 2–3 предложения о сути и прямая ссылка; "
              "3) что стоит прочитать в первую очередь и почему. "
              "Используй только заголовки и описания RSS ниже. Не заявляй, что прочитал полные статьи; не добавляй фактов без опоры на RSS. "
              "Если описания недостаточно, прямо скажи об этом. Пиши обычным текстом с заголовками и абзацами, без Markdown-таблиц.\n\n" + "\n\n".join(lines))
    compact_lines = [f"- {item['title']}" for item in articles[:7]]
    wormsoft_prompt = "Составь обзор тем этих публикаций Хабра на русском: 5–7 предложений и что читать сначала. Опирайся только на заголовки, не выдумывай содержание статей.\n" + "\n".join(compact_lines)
    if not call and os.environ.get("DAY18_DIGEST_MODE") == "plain":
        result = {"body": "", "provider": "plain", "model": None, "attempts": []}
    elif call:
        result = fallback(prompt, call=call)
    elif os.environ.get("DAY18_SIMULATE_PROVIDER_FAILURES") == "1":
        result = fallback(prompt, call=lambda *_: (_ for _ in ()).throw(ValueError("simulated outage")))
    else:
        result = fallback(prompt, call=lambda provider, text: generate(provider, wormsoft_prompt if provider == "wormsoft" else text))
    model_body = result["body"]
    body = ("Обзор модели\n" + model_body + "\n\nМатериалы и выдержки из RSS\n" + plain) if model_body else plain
    provider = result["provider"] or "plain"
    now = datetime.now(timezone.utc).isoformat()
    db = connect(db_path)
    try:
        with db:
            db.execute("INSERT INTO digests (created_at, provider, model, body, article_count, attempts_json) VALUES (?, ?, ?, ?, ?, ?)", (now, provider, result["model"], body, len(articles), json.dumps(result["attempts"])))
    finally:
        db.close()
    return {"created_at": now, "provider": provider, "model": result["model"], "article_count": len(articles), "body": body, "attempts": result["attempts"]}


def latest_digest(*, db_path=DB_PATH):
    db = connect(db_path)
    try:
        row = db.execute("SELECT created_at, provider, model, body, article_count, attempts_json FROM digests ORDER BY id DESC LIMIT 1").fetchone()
        digest = dict(row) if row else None
        if digest:
            digest["attempts"] = json.loads(digest.pop("attempts_json"))
        return {"digest": digest, "status": status(db_path)}
    finally:
        db.close()
