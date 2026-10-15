"""Веб-сервер дня 34: FastAPI, живая трасса агентных шагов, diff, сброс проекта."""
import asyncio
import os
from pathlib import Path
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import DAY, reset_project, run_agent
from mcp_client import FileToolSession
from model_provider import create_model, settings
from files_mcp_server import default_roots, tool_session_diff

WEB_PORT = int(os.environ.get('DAY34_WEB_PORT', '8834'))

SCENARIOS = [
    {'id': 'usage', 'title': 'Найти использования PriceCalculator',
     'goal': 'Найди все места в проекте, где используется класс PriceCalculator, '
             'и объясни, где именно считается итоговая цена корзины.'},
    {'id': 'changelog', 'title': 'Обновить CHANGELOG по коду',
     'goal': 'В коде проекта появилась поддержка промокодов, но CHANGELOG.md её не '
             'описывает. Изучи код и добавь запись о промокодах в раздел Unreleased.'},
    {'id': 'readme-check', 'title': 'Проверить README на соответствие коду',
     'goal': 'Проверь, что README.md соответствует коду проекта (структура, пример '
             'использования, список возможностей), и исправь устаревшие места.'},
]

app = FastAPI(title='День 34 — файловый ассистент', docs_url=None, redoc_url=None)
RUNS = {}
LOCK = threading.Lock()


class RunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)


def _run_worker(run_id, goal):
    def on_step(step):
        with LOCK:
            RUNS[run_id]['steps'].append({k: v for k, v in step.items()})
    try:
        result = asyncio.run(run_agent(goal, on_step=on_step))
        with LOCK:
            RUNS[run_id].update(status='done', answer=result['answer'],
                diff=result['diff'], changed_files=result['changed_files'],
                model=result['model'], tool_calls=result['tool_calls'],
                duration_ms=result['duration_ms'])
    except Exception as exc:
        partial = {}
        try:
            partial = tool_session_diff(*default_roots())
        except Exception as diff_exc:
            partial['diff_error'] = f'{type(diff_exc).__name__}: {diff_exc}'
        with LOCK:
            RUNS[run_id].update(status='error', error=f'{type(exc).__name__}: {exc}', **partial)


@app.get('/api/bootstrap')
def bootstrap():
    async def catalog():
        async with FileToolSession() as session:
            return {'server': session.server_name,
                    'protocol_version': session.protocol_version,
                    'tools': session.catalog}
    try:
        mcp_info = asyncio.run(catalog())
    except Exception as exc:
        raise HTTPException(503, f'MCP недоступен: {type(exc).__name__}: {exc}') from None
    provider, model = settings()
    project, baseline = default_roots()
    baseline_ok = baseline.is_dir() and project.is_dir()
    return {'mcp': mcp_info, 'provider': provider, 'model': model,
            'scenarios': SCENARIOS, 'baseline_ok': baseline_ok,
            'max_steps': 12}


@app.post('/api/runs', status_code=201)
def start_run(request: RunRequest):
    goal = request.goal.strip()
    if not goal:
        raise HTTPException(422, 'цель не должна быть пустой')
    with LOCK:
        busy = any(r['status'] == 'running' for r in RUNS.values())
        if busy:
            raise HTTPException(409, 'уже выполняется другой прогон; дождитесь завершения')
        run_id = uuid.uuid4().hex[:8]
        RUNS[run_id] = {'id': run_id, 'goal': goal, 'status': 'running', 'steps': [],
                        'created': time.time()}
    thread = threading.Thread(target=_run_worker, args=(run_id, goal), daemon=True)
    thread.start()
    return {'run_id': run_id}


@app.get('/api/runs/{run_id}')
def get_run(run_id: str):
    with LOCK:
        run = RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, 'прогон не найден')
        return dict(run)


@app.post('/api/reset')
def reset():
    with LOCK:
        busy = any(r['status'] == 'running' for r in RUNS.values())
        if busy:
            raise HTTPException(409, 'нельзя сбрасывать проект во время прогона')
        try:
            return reset_project(os.environ.get('DAY34_PROJECT_ROOT') or None,
                                 os.environ.get('DAY34_BASELINE_ROOT') or None)
        except ValueError as exc:
            raise HTTPException(500, str(exc)) from None


@app.get('/healthz')
def healthz():
    project, baseline = default_roots()
    return {'ok': project.is_dir(), 'project_root': str(project),
            'baseline_ok': baseline.is_dir()}


@app.get('/')
def index():
    return FileResponse(DAY / 'web' / 'index.html')


app.mount('/static', StaticFiles(directory=DAY / 'web'), name='static')


def main():
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=WEB_PORT, log_level='warning')


if __name__ == '__main__':
    main()
