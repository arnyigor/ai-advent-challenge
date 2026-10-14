"""SrokOK product and support service. Run: python server.py."""
import asyncio
from collections import defaultdict, deque
from datetime import date
import json
import logging
import re
import secrets
import time
from typing import Annotated
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from crm_client import crm_call
from generation import generate, ProviderError
from retrieval import Index
from settings import DAY, DATA, HOST, PORT, MODEL, DAILY_LIMIT, SECURE_COOKIE, TIMEZONE
from store import Store

app = FastAPI(title='СрокОК', docs_url=None, redoc_url=None, openapi_url=None)
store, index = Store(), Index()
slots = asyncio.Semaphore(2)
active_chats = set()
rates = defaultdict(deque)
logger = logging.getLogger('srokok')


class Chat(BaseModel):
    ticket_id: Annotated[str, Field(pattern=r'^SK-\d{4}$')]
    message: Annotated[str, Field(min_length=1, max_length=1200)]

    @field_validator('message')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Напишите вопрос')
        return value.strip()


class Purchase(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    store: Annotated[str, Field(max_length=100)] = ''
    purchased: date
    months: Annotated[int, Field(ge=1, le=120, strict=True)]
    note: Annotated[str, Field(max_length=500)] = ''

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Укажите название')
        return value.strip()

    @field_validator('purchased')
    @classmethod
    def plausible_date(cls, value):
        if not date(1970, 1, 1) <= value <= date(2100, 12, 31):
            raise ValueError('Дата должна быть между 1970 и 2100 годом')
        return value


@app.middleware('http')
async def session_and_safety(request: Request, call_next):
    sid = request.cookies.get('srokok_session', '')
    new = not re.fullmatch(r'[a-f0-9]{48}', sid)
    if new:
        sid = secrets.token_hex(24)
    request.state.session = sid
    if request.method == 'POST':
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': 'Запрос должен идти с этой страницы'}, status_code=403)
        if len(await request.body()) > 8192:
            return JSONResponse({'detail': 'Запрос слишком большой'}, status_code=413)
    response = await call_next(request)
    if new:
        response.set_cookie('srokok_session', sid, httponly=True, samesite='lax',
            secure=SECURE_COOKIE, max_age=60 * 60 * 24 * 365)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
    return response


async def read_context(ticket_id):
    try:
        result = await crm_call('get_ticket_context', {'ticket_id': ticket_id})
    except Exception:
        logger.warning('MCP context unavailable')
        raise HTTPException(503, 'CRM временно недоступна. Повторите позже.') from None
    if result[0].get('not_found'):
        raise HTTPException(404, 'Тикет не найден')
    return result


@app.get('/healthz')
def health():
    with store.connect() as db:
        db.execute('SELECT 1').fetchone()
    return {'status': 'ok', 'product': 'СрокОК', 'index_version': index.version,
        'chunks': len(index.chunks), 'timezone': str(TIMEZONE)}


@app.get('/api/bootstrap')
async def bootstrap():
    try:
        payload, trace = await crm_call('list_tickets')
    except Exception:
        raise HTTPException(503, 'Не удалось загрузить CRM. Попробуйте обновить страницу.') from None
    return {'product': 'СрокОК', 'version': '1.0', 'demo_crm': True,
        'tickets': payload['tickets'], 'mcp': trace, 'model': MODEL,
        'knowledge': [{k: d[k] for k in ('id', 'title')} for d in index.documents.values()],
        'index': {'version': index.version, 'chunks': len(index.chunks), 'method': 'BM25'}}


@app.get('/api/tickets/{ticket_id}')
async def ticket(ticket_id: str, request: Request):
    context, trace = await read_context(ticket_id)
    return {'context': context, 'mcp': trace,
        'history': store.history(request.state.session, ticket_id)}


@app.post('/api/chat')
async def chat(body: Chat, request: Request):
    sid, now = request.state.session, time.monotonic()
    # Bound limiter memory, then apply one shared per-visitor minute quota.
    for key in list(rates):
        if not rates[key] or rates[key][-1] < now - 60:
            del rates[key]
    recent = rates[sid]
    while recent and recent[0] < now - 60:
        recent.popleft()
    if len(recent) >= 6:
        raise HTTPException(429, 'До 6 вопросов в минуту. Подождите немного.')
    recent.append(now)
    chat_key = (sid, body.ticket_id)
    if chat_key in active_chats:
        raise HTTPException(409, 'Предыдущий ответ для этого тикета ещё готовится')
    active_chats.add(chat_key)
    acquired = False
    try:
        try:
            await asyncio.wait_for(slots.acquire(), timeout=5)
            acquired = True
        except TimeoutError:
            raise HTTPException(429, 'Ассистент занят. Повторите через несколько секунд.') from None
        context, trace = await read_context(body.ticket_id)
        history = store.history(sid, body.ticket_id, limit=8)
        previous = ' '.join(m['content']['text'] for m in history if m['role'] == 'user')
        related = context['ticket']['description'] + ' ' + json.dumps(context['ticket']['events'], ensure_ascii=False)
        sources = index.search(body.message, previous[-1600:] + ' ' + related)
        try:
            store.reserve_generation(DAILY_LIMIT)
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from None
        compact_history = [{'role': m['role'], 'text': m['content'].get('text') or
            '\n'.join(p['text'] for p in m['content'].get('paragraphs', []))} for m in history]
        grounded_context = context if sources else {'product': 'СрокОК', 'ticket_id': body.ticket_id,
            'note': 'Нет документов, соответствующих этому вопросу. Не отвечай на другой вопрос из тикета.'}
        generated = await generate(body.message, grounded_context, sources, compact_history if sources else [])
        response = dict(generated, sources=sources, mcp=trace,
            index_version=index.version, ticket_id=body.ticket_id,
            elapsed_ms=round((time.monotonic() - now) * 1000))
        store.save_exchange(sid, body.ticket_id, body.message, response)
        return response
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    finally:
        active_chats.discard(chat_key)
        if acquired:
            slots.release()


@app.get('/api/purchases')
def purchases(request: Request):
    return {'items': store.purchases(request.state.session)}


@app.post('/api/purchases', status_code=201)
def add_purchase(body: Purchase, request: Request):
    try:
        return store.add_purchase(request.state.session, body.model_dump(mode='json'))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get('/api/purchases/export')
def export(request: Request):
    return JSONResponse({'product': 'СрокОК', 'items': store.purchases(request.state.session)},
        headers={'Content-Disposition': 'attachment; filename="srokok-purchases.json"'})


@app.get('/api/knowledge/{document_id}')
def knowledge(document_id: str):
    if document_id not in index.documents:
        raise HTTPException(404, 'Статья не найдена')
    return index.documents[document_id]


@app.get('/')
def page():
    return FileResponse(DAY / 'web' / 'index.html')


@app.get('/demo.mp4')
def demo_video():
    path = DATA / 'demo.mp4'
    if not path.is_file():
        raise HTTPException(404, 'Видео ещё не опубликовано')
    return FileResponse(path, media_type='video/mp4')


@app.get('/code.zip')
def source_archive():
    path = DATA / 'code.zip'
    if not path.is_file():
        raise HTTPException(404, 'Архив ещё не опубликован')
    return FileResponse(path, media_type='application/zip', filename='day33-srokok-code.zip')


@app.get('/{asset}')
def asset(asset: str):
    if asset not in {'app.js', 'style.css', 'icon.svg'}:
        raise HTTPException(404)
    return FileResponse(DAY / 'web' / asset)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, proxy_headers=True, forwarded_allow_ips='127.0.0.1')
