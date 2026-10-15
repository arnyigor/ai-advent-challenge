"""Агентный цикл дня 34: модель сама выбирает файловые инструменты MCP.

Протокол: на каждом шаге модель возвращает строго один JSON-объект —
{"action": "tool", "name": ..., "arguments": {...}, "thought": "..."} или
{"action": "final", "answer": "..."}. Сервер исполняет вызов через настоящий
MCP stdio-клиент и добавляет результат в транскрипт. Лимит MAX_STEPS шагов.
"""
import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

from mcp_client import FileToolSession
from model_provider import create_model

DAY = Path(__file__).resolve().parent
MAX_STEPS = 12
MAX_STEP_RESULT = 4000
MAX_PARSE_RETRIES = 2

SYSTEM = (
    'Ты ассистент разработчика, работающий с файлами проекта через инструменты MCP. '
    'Пользователь ставит ЦЕЛЬ, а ты САМ решаешь, какие инструменты вызывать. '
    'На каждом шаге отвечай СТРОГО одним JSON-объектом без markdown и пояснений: '
    '{"action": "tool", "name": "<инструмент>", "arguments": {...}, "thought": "<почему этот шаг>"} '
    'или {"action": "final", "answer": "<итоговый ответ по-русски>"}. '
    'Правила: сначала изучи проект (list_files, search_files, read_file), только потом '
    'изменяй файлы (replace_in_file, write_file); перед правкой прочитай изменяемый файл; '
    'не выдумывай файлы и строки — опирайся на результаты инструментов; в ответе ссылайся '
    'на файлы как path:line; если цель выполнена и файлы менялись, вызови session_diff '
    'перед финальным ответом; если данных недостаточно, честно скажи об этом в final. '
    'Пути всегда относительные от корня проекта.')


def parse_step(text: str) -> dict:
    """Один JSON-шаг из ответа модели; терпим к обёртке ```json ... ```."""
    if not isinstance(text, str):
        raise ValueError('пустой ответ модели')
    start = text.find('{')
    if start < 0:
        raise ValueError('в ответе нет JSON-объекта')
    try:
        step, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f'невалидный JSON: {exc}') from None
    if not isinstance(step, dict) or step.get('action') not in ('tool', 'final'):
        raise ValueError('шаг: action должен быть "tool" или "final"')
    if step['action'] == 'tool':
        if not isinstance(step.get('name'), str) or not step['name'].strip():
            raise ValueError('шаг tool: пустое name')
        if not isinstance(step.get('arguments', {}), dict):
            raise ValueError('шаг tool: arguments должен быть объектом')
        step.setdefault('arguments', {})
    else:
        answer = step.get('answer')
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError('шаг final: пустой answer')
        step['answer'] = answer.strip()
    return step


def _catalog_text(catalog) -> str:
    blocks = []
    for tool in catalog:
        schema = json.dumps(tool['inputSchema'], ensure_ascii=False)
        blocks.append(f"- {tool['name']}: {tool['description']}\n  inputSchema: {schema}")
    return '\n'.join(blocks)


def _transcript(goal: str, catalog_text: str, history: list) -> str:
    parts = [f'ИНСТРУМЕНТЫ MCP (каталог получен из tools/list):\n{catalog_text}',
             f'\nЦЕЛЬ ПОЛЬЗОВАТЕЛЯ:\n{goal}']
    for item in history:
        parts.append('\n' + item)
    parts.append('\nСледующий шаг — строго один JSON-объект по протоколу.')
    return '\n'.join(parts)


async def run_agent(goal: str, model=None, session=None, max_steps: int = MAX_STEPS,
                    on_step=None) -> dict:
    """Полный прогон: цель → шаги (tool calls через MCP) → финальный ответ + diff."""
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 1000:
        raise ValueError('цель: от 1 до 1000 символов')
    model = model or create_model()
    if session is None:
        session = FileToolSession()
    manager = session if session.session is None else _reuse(session)
    started = time.monotonic()
    async with manager as tools:
        catalog_text = _catalog_text(tools.catalog)
        history, steps, answer = [], [], None
        parse_errors = 0
        for number in range(1, max_steps + 1):
            prompt = _transcript(goal.strip(), catalog_text, history)
            step_started = time.monotonic()
            raw = (await asyncio.to_thread(model.generate, SYSTEM, prompt))['answer']
            try:
                step = parse_step(raw)
                parse_errors = 0
            except ValueError as exc:
                parse_errors += 1
                history.append(f'ОШИБКА ПРОТОКОЛА: {exc}. Ответь строго одним JSON-объектом.')
                if parse_errors > MAX_PARSE_RETRIES:
                    raise RuntimeError(f'модель не следует протоколу: {exc}') from None
                continue
            if step['action'] == 'final':
                answer = step['answer']
                steps.append({'n': number, 'action': 'final',
                              'duration_ms': int((time.monotonic() - step_started) * 1000)})
                if on_step:
                    on_step(steps[-1])
                break
            name, arguments = step['name'], step['arguments']
            thought = str(step.get('thought', ''))[:500]
            record = {'n': number, 'action': 'tool', 'tool': name,
                      'arguments': arguments, 'thought': thought}
            try:
                payload = await tools.call(name, arguments)
                record['result'] = payload
                result_text = json.dumps(payload, ensure_ascii=False)
            except (RuntimeError, ValueError) as exc:
                record['error'] = str(exc)[:500]
                result_text = 'ОШИБКА ИНСТРУМЕНТА: ' + record['error']
            record['duration_ms'] = int((time.monotonic() - step_started) * 1000)
            steps.append(record)
            if on_step:
                on_step(record)
            if len(result_text) > MAX_STEP_RESULT:
                result_text = result_text[:MAX_STEP_RESULT] + '... (обрезано)'
            history.append(f'ШАГ {number}. Мысль: {thought}\n'
                           f'ВЫЗОВ: {name} {json.dumps(arguments, ensure_ascii=False)}\n'
                           f'РЕЗУЛЬТАТ: {result_text}')
        if answer is None:
            raise RuntimeError(f'цель не достигнута за {max_steps} шагов')
        # Always measure the final state: the model may edit after session_diff.
        # A failed diff must remain visible, never look like an unchanged project.
        diff = await tools.call('session_diff', {})
        return {'goal': goal.strip(), 'answer': answer, 'steps': steps,
                'tool_calls': sum(1 for s in steps if s['action'] == 'tool'),
                'changed_files': diff.get('changed_files', []), 'diff': diff.get('diff', ''),
                'model': model.label, 'mcp_server': tools.server_name,
                'protocol_version': tools.protocol_version, 'catalog': tools.catalog,
                'duration_ms': int((time.monotonic() - started) * 1000)}


class _reuse:
    """async-контекст без закрытия: сессию предоставил вызывающий."""
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


def reset_project(project_root=None, baseline_root=None) -> dict:
    project = Path(project_root or DAY / 'sample_project').resolve()
    baseline = Path(baseline_root or DAY / 'baseline').resolve()
    if not baseline.is_dir():
        raise ValueError('baseline не найден')
    if (project == baseline or project in baseline.parents or baseline in project.parents
            or project == Path(project.anchor) or project == DAY.parent.resolve()
            or project in DAY.resolve().parents):
        raise ValueError('небезопасный корень сброса: нужен отдельный каталог проекта')
    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(baseline, project)
    files = sorted(str(p.relative_to(project).as_posix()) for p in project.rglob('*') if p.is_file())
    return {'reset': True, 'files': files}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goal', help='цель на уровне задачи, например: обнови CHANGELOG')
    parser.add_argument('--reset', action='store_true', help='восстановить sample_project из baseline')
    parser.add_argument('--catalog', action='store_true', help='показать каталог MCP-инструментов')
    args = parser.parse_args()
    try:
        if args.reset:
            print(json.dumps(reset_project(), ensure_ascii=False, indent=2))
            return 0
        if args.catalog:
            async def show():
                async with FileToolSession() as session:
                    return {'server': session.server_name, 'catalog': session.catalog}
            print(json.dumps(asyncio.run(show()), ensure_ascii=False, indent=2))
            return 0
        if not args.goal:
            parser.print_help()
            return 0
        result = asyncio.run(run_agent(args.goal))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f'Ошибка: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
