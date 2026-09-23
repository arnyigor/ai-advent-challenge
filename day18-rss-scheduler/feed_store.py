"""Fetch the Habr AI RSS feed and store new entries in SQLite."""

import os
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

FEED_URL = "https://habr.com/ru/rss/hub/artificial_intelligence/articles/"
DB_PATH = Path(os.environ.get("DAY18_DB_PATH", Path(__file__).with_name("feed.sqlite3")))


def connect(path=DB_PATH):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("CREATE TABLE IF NOT EXISTS articles (url TEXT PRIMARY KEY, title TEXT NOT NULL, published TEXT, description TEXT, discovered_at TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, ran_at TEXT NOT NULL, found INTEGER NOT NULL, inserted INTEGER NOT NULL, error TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS digests (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, provider TEXT NOT NULL, model TEXT, body TEXT NOT NULL, article_count INTEGER NOT NULL, attempts_json TEXT NOT NULL DEFAULT '[]')")
    db.execute("CREATE TABLE IF NOT EXISTS schedule_state (job TEXT PRIMARY KEY, interval_seconds INTEGER NOT NULL, last_at TEXT, next_at TEXT NOT NULL, last_result TEXT)")
    if "attempts_json" not in [row[1] for row in db.execute("PRAGMA table_info(digests)")]:
        db.execute("ALTER TABLE digests ADD COLUMN attempts_json TEXT NOT NULL DEFAULT '[]'")
    db.commit()
    return db


def parse_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    entries = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if title and url.startswith("https://habr.com/"):
            entries.append((url, title, (item.findtext("pubDate") or "").strip(), (item.findtext("description") or "").strip()))
    return entries


def collect(*, db_path=DB_PATH, feed_url=FEED_URL, fetch=None):
    now = datetime.now(timezone.utc).isoformat()
    db = connect(db_path)
    try:
        try:
            response = (fetch or requests.get)(feed_url, timeout=20, headers={"User-Agent": "AIAdventChallenge/18 RSS reader"})
            response.raise_for_status()
            entries = parse_feed(response.content)
            if not entries:
                raise ValueError("RSS returned no usable articles")
            before = db.total_changes
            with db:
                db.executemany("INSERT OR IGNORE INTO articles VALUES (?, ?, ?, ?, ?)", [(*entry, now) for entry in entries])
                inserted = db.total_changes - before
                db.execute("INSERT INTO runs (ran_at, found, inserted, error) VALUES (?, ?, ?, NULL)", (now, len(entries), inserted))
            return {"found": len(entries), "inserted": inserted, "ran_at": now}
        except Exception as exc:
            with db:
                db.execute("INSERT INTO runs (ran_at, found, inserted, error) VALUES (?, 0, 0, ?)", (now, f"{type(exc).__name__}: {exc}",))
            raise
    finally:
        db.close()


def recent_articles(db_path=DB_PATH, *, limit=12, since=None):
    db = connect(db_path)
    try:
        return [dict(row) for row in db.execute("SELECT url, title, published, description, discovered_at FROM articles WHERE (? IS NULL OR discovered_at > ?) ORDER BY discovered_at DESC, published DESC LIMIT ?", (since, since, limit))]
    finally:
        db.close()


def status(db_path=DB_PATH):
    db = connect(db_path)
    try:
        return {"articles": db.execute("SELECT count(*) FROM articles").fetchone()[0], "last_run": dict(row) if (row := db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()) else None}
    finally:
        db.close()


def recent_runs(db_path=DB_PATH, *, limit=8):
    db = connect(db_path)
    try:
        return [dict(row) for row in db.execute("SELECT ran_at, found, inserted, error FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        db.close()


def reset_state(db_path=DB_PATH):
    """Clear only Day 18 demo data; keep the schedule configuration."""
    db = connect(db_path)
    try:
        with db:
            for table in ("articles", "runs", "digests"):
                db.execute(f"DELETE FROM {table}")
            db.execute("UPDATE schedule_state SET last_at=NULL, last_result=NULL")
        return {"articles": 0, "runs": 0, "digests": 0}
    finally:
        db.close()
