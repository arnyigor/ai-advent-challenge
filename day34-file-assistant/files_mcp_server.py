"""Файловые инструменты ассистента через MCP stdio. Только sandbox-корень.

Вся логика — в чистых функциях (их покрывают unit-тесты); декораторы MCP
только публикуют их наружу. Корень проекта: DAY34_PROJECT_ROOT, baseline для
session_diff: DAY34_BASELINE_ROOT. Запреты: path traversal, симлинки наружу,
скрытые файлы, секреты по имени, бинарное содержимое, файлы больше MAX_FILE.
"""
import difflib
import os
from pathlib import Path
import re
import tempfile

from mcp.server import MCPServer

MAX_FILE = 200 * 1024
MAX_WRITE = 100 * 1024
MAX_READ_LINES = 400
MAX_LIST = 200
MAX_SEARCH_RESULTS = 20
MAX_SCAN_FILES = 500
MAX_DIFF_CHARS = 12000

mcp = MCPServer('day34-files', version='1.0.0', log_level='WARNING')

_DENIED_SUFFIXES = {'.pem', '.key', '.pfx', '.p12'}
_DENIED_NAMES = {'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', 'credentials'}


def default_roots():
    day = Path(__file__).resolve().parent
    root = Path(os.environ.get('DAY34_PROJECT_ROOT', day / 'sample_project')).resolve()
    baseline = Path(os.environ.get('DAY34_BASELINE_ROOT', day / 'baseline')).resolve()
    return root, baseline


def _denied_name(name: str) -> bool:
    lowered = name.lower()
    return (name.startswith('.') or lowered in _DENIED_NAMES or 'secret' in lowered
            or Path(lowered).suffix in _DENIED_SUFFIXES or lowered == '.env'
            or lowered.startswith('.env.'))


def resolve_path(root: Path, rel: str) -> Path:
    """Относительный путь внутри root; ошибка при выходе, симлинке наружу,
    скрытых именах и именах, похожих на секреты."""
    if not isinstance(rel, str) or not rel.strip() or rel.strip() in ('.', './'):
        raise ValueError('path: нужен относительный путь к файлу')
    rel = rel.strip().replace('\\', '/')
    if rel.startswith('/') or ':' in rel:
        raise ValueError('path: абсолютные пути запрещены')
    parts = [p for p in rel.split('/') if p not in ('', '.')]
    if not parts or any(p == '..' for p in parts):
        raise ValueError('path: выход за пределы проекта запрещён')
    if any(_denied_name(p) for p in parts):
        raise ValueError('path: скрытые файлы и секреты недоступны')
    target = (root / Path(*parts)).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError('path: выход за пределы проекта запрещён')
    # симлинки внутри корня, ведущие наружу
    probe = root
    for part in parts[:-1]:
        probe = probe / part
        if probe.is_symlink() and not probe.resolve().is_relative_to(root):
            raise ValueError('path: симлинк за пределы проекта запрещён')
    return target


def _decode_text(data: bytes) -> str:
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('бинарный файл недоступен') from None
    if '\x00' in text:
        raise ValueError('бинарный файл недоступен')
    return text


def _read_text(target: Path) -> str:
    if not target.exists() or not target.is_file():
        raise ValueError('файл не найден')
    if target.stat().st_size > MAX_FILE:
        raise ValueError('файл больше 200 КБ')
    return _decode_text(target.read_bytes())


def _iter_files(root: Path, pattern: str):
    base = Path(pattern or '**/*')
    if base.is_absolute() or '..' in base.parts:
        raise ValueError('pattern: только относительный glob внутри проекта')
    count = 0
    for path in sorted(root.glob(str(base))):
        if count >= MAX_SCAN_FILES:
            break
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(_denied_name(p) for p in rel.parts):
            continue
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            continue
        if path.is_file():
            count += 1
            yield path, rel


def _unified_diff(old: str, new: str, rel: str) -> str:
    diff = ''.join(difflib.unified_diff(old.splitlines(keepends=True),
        new.splitlines(keepends=True), fromfile=f'a/{rel}', tofile=f'b/{rel}'))
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + '\n... (diff обрезан)\n'
    return diff


def tool_list_files(root: Path, path: str = '.', pattern: str = '**/*') -> dict:
    sub = root if path.strip() in ('.', './') else resolve_path(root, path)
    if not sub.is_dir():
        raise ValueError('path: каталог не найден')
    entries = []
    for file, rel in _iter_files(sub, pattern):
        entries.append({'path': rel.as_posix(), 'bytes': file.stat().st_size})
        if len(entries) >= MAX_LIST:
            break
    prefix = '' if sub == root else sub.relative_to(root).as_posix() + '/'
    return {'files': [{'path': prefix + e['path'], 'bytes': e['bytes']} for e in entries],
            'truncated': len(entries) >= MAX_LIST}


def tool_read_file(root: Path, path: str, start_line: int = 1, end_line: int | None = None) -> dict:
    text = _read_text(resolve_path(root, path))
    lines = text.splitlines()
    start = max(1, int(start_line))
    if end_line is not None and int(end_line) < start:
        raise ValueError('end_line должен быть не меньше start_line')
    stop = min(len(lines), start + MAX_READ_LINES - 1,
               int(end_line) if end_line is not None else len(lines))
    if start > len(lines) and lines:
        raise ValueError(f'start_line вне файла: всего {len(lines)} строк')
    body = '\n'.join(f'{n}: {lines[n - 1]}' for n in range(start, stop + 1))
    return {'path': path, 'total_lines': len(lines),
            'shown_lines': [start, stop], 'truncated': stop < len(lines), 'content': body}


def tool_search_files(root: Path, query: str, file_glob: str = '**/*',
                      max_results: int = MAX_SEARCH_RESULTS) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError('query: пустой запрос')
    try:
        pattern = re.compile(query)
    except re.error as exc:
        raise ValueError(f'query: невалидное регулярное выражение: {exc}') from None
    limit = min(max(1, int(max_results)), MAX_SEARCH_RESULTS)
    matches, scanned = [], 0
    for file, rel in _iter_files(root, file_glob):
        if len(matches) >= limit:
            break
        if file.stat().st_size > MAX_FILE:
            continue
        try:
            lines = _decode_text(file.read_bytes()).splitlines()
        except ValueError:
            continue
        scanned += 1
        for number, line in enumerate(lines, 1):
            if pattern.search(line):
                matches.append({'path': rel.as_posix(), 'line': number,
                                'text': line.strip()[:300]})
                if len(matches) >= limit:
                    break
    return {'query': query, 'files_scanned': scanned, 'matches': matches,
            'truncated': len(matches) >= limit}


def _atomic_write(target: Path, content: str):
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive temporary file: do not follow a pre-existing tmp symlink.
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(content.encode('utf-8'))
    try:
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _normalize_newlines(text: str) -> str:
    """Модели иногда присылают CRLF; в проекте держим LF, иначе diff раздувается."""
    return text.replace('\r\n', '\n').replace('\r', '\n')


def tool_write_file(root: Path, path: str, content: str) -> dict:
    if not isinstance(content, str):
        raise ValueError('content: ожидается строка')
    content = _normalize_newlines(content)
    if len(content.encode('utf-8')) > MAX_WRITE:
        raise ValueError('content: больше 100 КБ')
    target = resolve_path(root, path)
    old = _read_text(target) if target.exists() else ''
    created = not target.exists()
    _atomic_write(target, content)
    return {'path': path, 'created': created, 'lines': len(content.splitlines()),
            'diff': _unified_diff(old, content, path)}


def tool_replace_in_file(root: Path, path: str, old: str, new: str, count: int = 1) -> dict:
    if not old:
        raise ValueError('old: пустая строка поиска')
    old, new = _normalize_newlines(old), _normalize_newlines(new)
    target = resolve_path(root, path)
    text = _read_text(target)
    found = text.count(old)
    expected = max(1, int(count))
    if found == 0:
        raise ValueError('old: фрагмент не найден, файл не изменён')
    if found != expected:
        raise ValueError(f'old: найдено {found} вхождений, ожидалось {expected}; '
                         'уточните фрагмент или count, файл не изменён')
    updated = text.replace(old, new, expected)
    if len(updated.encode('utf-8')) > MAX_WRITE:
        raise ValueError('результат больше 100 КБ')
    _atomic_write(target, updated)
    return {'path': path, 'replacements': found,
            'diff': _unified_diff(text, updated, path)}


def tool_session_diff(root: Path, baseline: Path) -> dict:
    if not baseline.is_dir():
        raise ValueError('baseline не найден')
    changed, diffs = [], []
    for file, rel in _iter_files(root, '**/*'):
        original = baseline / rel
        old = ''
        if original.is_file():
            try:
                old = _decode_text(original.read_bytes())
            except ValueError:
                continue
        try:
            new = _decode_text(file.read_bytes())
        except ValueError:
            continue
        if new != old:
            changed.append(rel.as_posix())
            diffs.append(_unified_diff(old, new, rel.as_posix()))
    return {'changed_files': changed, 'diff': '\n'.join(d for d in diffs if d)}


# --- публикация через MCP ---

@mcp.tool(description='Список файлов проекта (относительные пути и размеры). '
                      'path — подкаталог от корня проекта, pattern — glob вроде **/*.py.')
def list_files(path: str = '.', pattern: str = '**/*') -> dict:
    root, _ = default_roots()
    return tool_list_files(root, path, pattern)


@mcp.tool(description='Читает файл проекта с номерами строк. start_line с 1, '
                      'end_line необязателен; максимум 400 строк за вызов.')
def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> dict:
    root, _ = default_roots()
    return tool_read_file(root, path, start_line, end_line)


@mcp.tool(description='Поиск по всем файлам проекта: регулярное выражение, '
                      'совпадения path:line и строка контекста. file_glob сужает набор файлов.')
def search_files(query: str, file_glob: str = '**/*', max_results: int = 20) -> dict:
    root, _ = default_roots()
    return tool_search_files(root, query, file_glob, max_results)


@mcp.tool(description='Создаёт или полностью перезаписывает файл в проекте. '
                      'Возвращает unified diff изменения. Секреты и скрытые файлы запрещены.')
def write_file(path: str, content: str) -> dict:
    root, _ = default_roots()
    return tool_write_file(root, path, content)


@mcp.tool(description='Точечная правка файла: заменяет ровно count вхождений фрагмента old '
                      'на new (по умолчанию 1). Если вхождений другое число — ошибка, файл '
                      'не изменяется. Возвращает unified diff.')
def replace_in_file(path: str, old: str, new: str, count: int = 1) -> dict:
    root, _ = default_roots()
    return tool_replace_in_file(root, path, old, new, count)


@mcp.tool(description='Объединённый unified diff всех изменений проекта за сессию '
                      'относительно эталонного снимка. Вызывай в конце задачи, '
                      'которую поручено показать как diff.')
def session_diff() -> dict:
    root, baseline = default_roots()
    return tool_session_diff(root, baseline)


if __name__ == '__main__':
    mcp.run(transport='stdio')
