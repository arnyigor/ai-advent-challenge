"""SQLite persistence; every personal row is scoped to the server session."""
import calendar
from contextlib import contextmanager
from datetime import date, datetime
import json
import sqlite3
import uuid
from settings import DATA, TIMEZONE


def warranty_end(purchased: date, months: int):
    total = purchased.year * 12 + purchased.month - 1 + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    return date(year, month, min(purchased.day, calendar.monthrange(year, month)[1]))


class Store:
    def __init__(self, path=None):
        self.path = path or DATA / 'support.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS purchases(
                    id TEXT PRIMARY KEY, session TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS purchase_session ON purchases(session);
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY, session TEXT NOT NULL, ticket TEXT NOT NULL,
                    role TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS message_session ON messages(session,ticket);
                CREATE TABLE IF NOT EXISTS quota(day TEXT PRIMARY KEY, used INTEGER NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            with db:
                yield db
        finally:
            db.close()

    def add_purchase(self, session, body):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM purchases WHERE session=?', (session,)).fetchone()[0] >= 500:
                raise ValueError('Лимит: 500 покупок на кабинет')
            item = dict(body, id=uuid.uuid4().hex,
                expires=warranty_end(date.fromisoformat(body['purchased']), body['months']).isoformat())
            db.execute('INSERT INTO purchases VALUES(?,?,?)', (item['id'], session, json.dumps(item, ensure_ascii=False)))
        return item

    def purchases(self, session):
        today = datetime.now(TIMEZONE).date()
        with self.connect() as db:
            items = [json.loads(r[0]) for r in db.execute('SELECT body FROM purchases WHERE session=?', (session,))]
        for item in items:
            item['days_left'] = (date.fromisoformat(item['expires']) - today).days
            item['status'] = 'expired' if item['days_left'] < 0 else 'soon' if item['days_left'] <= 30 else 'active'
        return sorted(items, key=lambda i: i['expires'])

    def history(self, session, ticket, limit=20):
        with self.connect() as db:
            rows = db.execute('SELECT role,body,created FROM messages WHERE session=? AND ticket=? ORDER BY id DESC LIMIT ?',
                (session, ticket, limit)).fetchall()
        return [{'role': r['role'], 'content': json.loads(r['body']), 'created': r['created']} for r in reversed(rows)]

    def save_exchange(self, session, ticket, question, response):
        now = datetime.now(TIMEZONE).isoformat()
        with self.connect() as db:
            for role, body in [('user', {'text': question}), ('assistant', response)]:
                db.execute('INSERT INTO messages(session,ticket,role,body,created) VALUES(?,?,?,?,?)',
                    (session, ticket, role, json.dumps(body, ensure_ascii=False), now))

    def reserve_generation(self, daily_limit):
        day = datetime.now(TIMEZONE).date().isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO quota VALUES(?,0)', (day,))
            used = db.execute('SELECT used FROM quota WHERE day=?', (day,)).fetchone()[0]
            if used >= daily_limit:
                raise ValueError('Дневной лимит AI исчерпан. Попробуйте завтра; статьи доступны сейчас.')
            db.execute('UPDATE quota SET used=used+1 WHERE day=?', (day,))
