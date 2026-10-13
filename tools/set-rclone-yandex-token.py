"""Положить OAuth-токен Яндекса в секцию rclone-конфига.

Запускает человек вручную: токен вводится в консоли скрыто и никуда не пишется,
кроме самого rclone.conf. Перед правкой делается резервная копия файла.

    .venv\\Scripts\\python.exe tools\\set-rclone-yandex-token.py
    .venv\\Scripts\\python.exe tools\\set-rclone-yandex-token.py --config D:\\rclone.conf

Для нестандартной секции: --remote yandex_backup
"""

import argparse
import datetime
import getpass
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_REMOTE = 'yandex_challenge'
TOKEN_PREFIX = 'y0_'
TOKEN_TTL_DAYS = 364


def default_config_path():
    appdata = os.environ.get('APPDATA')
    base = Path(appdata) if appdata else Path.home() / 'AppData' / 'Roaming'
    return base / 'rclone' / 'rclone.conf'


def get_remote_name(remote):
    """Имя секции rclone: 'yandex_challenge' или 'yandex_challenge:'."""
    return remote.strip().rstrip(':').strip()


def section_range(lines, name):
    """Границы секции [name] как полуинтервал индексов строк (start, end)."""
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if start is not None:
                return start, index
            if stripped[1:-1].strip() == name:
                start = index
    if start is not None:
        return start, len(lines)
    return None


def token_line(token, newline='\n', now=None):
    now = now or datetime.datetime.now().astimezone()
    expiry = (now + datetime.timedelta(days=TOKEN_TTL_DAYS)).replace(microsecond=0)
    payload = (
        '{"access_token":"%s","token_type":"OAuth","refresh_token":"none","expiry":"%s"}'
        % (token, expiry.isoformat())
    )
    return 'token = %s%s' % (payload, newline)


def masked(token):
    head = token[:8] if len(token) > 8 else token[:2]
    return '%s… (%d символов)' % (head, len(token))


def masked_line(line):
    """Показать строку token без самого токена."""
    marker = '"access_token":"'
    if marker not in line:
        return line.strip()
    start = line.index(marker) + len(marker)
    end = line.find('"', start)
    if end < 0:
        return line.strip()
    return '%s%s%s' % (line[:start], '***', line[end:])


def read_token(force):
    if sys.stdin is not None and not sys.stdin.isatty():
        token = sys.stdin.readline().strip()
        print('Токен прочитан со стандартного ввода.')
    else:
        # ASCII-приглашение: кириллица в getpass может поехать в консоли cp866.
        token = getpass.getpass('Yandex token (input hidden): ').strip()
    if not token:
        sys.exit('Токен пустой — ничего не меняю.')
    if not token.startswith(TOKEN_PREFIX):
        message = 'Токен не начинается с %r — похоже, скопировано не то.' % TOKEN_PREFIX
        if not force:
            sys.exit(message + ' Если это точно токен, повторите с --force.')
        print('ВНИМАНИЕ: ' + message, file=sys.stderr)
    if ' ' in token or '\t' in token:
        sys.exit('В токене есть пробельные символы — скопируйте его ещё раз без переносов.')
    return token


def read_lines(path):
    with open(path, 'r', encoding='utf-8', newline='') as handle:
        raw = handle.read()
    return raw, raw.splitlines(keepends=True)


def write_lines(path, lines):
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(''.join(lines))


def patch_config(path, remote, token, now=None):
    raw, lines = read_lines(path)
    newline = '\r\n' if '\r\n' in raw else '\n'
    bounds = section_range(lines, remote)
    if bounds is None:
        sys.exit(
            'В %s нет секции [%s]. Сначала создайте remote: rclone config (тип yandex).'
            % (path, remote)
        )
    start, end = bounds
    new_line = token_line(token, newline=newline, now=now)
    for index in range(start + 1, end):
        stripped = lines[index].lstrip()
        if stripped.startswith('token') and stripped[len('token'):].lstrip().startswith('='):
            previous = lines[index].strip()
            lines[index] = new_line
            break
    else:
        previous = '(строки token не было)'
        lines.insert(start + 1, new_line)

    backup = path.with_name(path.name + '.bak-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(path, backup)
    write_lines(path, lines)
    return backup, previous


def extract_token(path, remote):
    """Вернуть access_token из секции конфига или None."""
    raw, lines = read_lines(path)
    bounds = section_range(lines, remote)
    if bounds is None:
        sys.exit('В %s нет секции [%s].' % (path, remote))
    start, end = bounds
    for index in range(start + 1, end):
        stripped = lines[index].lstrip()
        if stripped.startswith('token') and stripped[len('token'):].lstrip().startswith('='):
            payload = stripped.split('=', 1)[1].strip()
            try:
                return json.loads(payload).get('access_token') or ''
            except ValueError:
                return ''
    return None


def check_config(path, remote):
    token = extract_token(path, remote)
    if token is None:
        sys.exit('В секции [%s] нет строки token — нечего проверять.' % remote)
    print('Файл:   %s' % path)
    print('Секция: [%s]' % remote)
    if not token:
        print('Токен:  НЕ РАСПОЗНАН (строка token есть, но JSON не разобрался)')
        return 1
    print('Токен:  %s…  длина %d' % (token[:4], len(token)))
    odd = sorted({ch for ch in token if not (ch.isalnum() or ch in '_-')})
    print('Начинается с y0_: %s' % ('да' if token.startswith('y0_') else 'НЕТ'))
    print('Подозрительные символы: %s' % (''.join(odd) if odd else 'нет'))
    if len(token) < 40:
        print('ВНИМАНИЕ: токен короче 40 символов — похоже, скопирован не целиком.')
    if any(mark in token for mark in ('****', 'access_token=', 'token_type=')):
        print('ВНИМАНИЕ: в токене остатки текста ссылки/маски.')
    return 0


def check_live(token):
    request = urllib.request.Request(
        'https://cloud-api.yandex.net/v1/disk/',
        headers={'Authorization': 'Bearer ' + token},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        print('Живой запрос к API: HTTP %s, всего %s байт — токен работает.' % (response.status, data.get('total_space')))
        return 0
    except urllib.error.HTTPError as error:
        body = error.read().decode('utf-8', 'replace')[:200]
        print('Живой запрос к API: HTTP %s %s' % (error.code, error.reason))
        print('Ответ Яндекса: %s' % body)
        return 1
    except OSError as error:
        print('Живой запрос к API не удался: %s' % error)
        return 1


def main():
    parser = argparse.ArgumentParser(description='Записать токен Яндекса в rclone.conf')
    parser.add_argument('--config', default=None, help='путь к rclone.conf (по умолчанию %%APPDATA%%\\rclone\\rclone.conf)')
    parser.add_argument('--remote', default=DEFAULT_REMOTE, help='имя remote (по умолчанию %s)' % DEFAULT_REMOTE)
    parser.add_argument('--force', action='store_true', help='принять токен, не начинающийся с y0_')
    parser.add_argument('--check', action='store_true', help='проверить токен в конфиге и живым запросом, ничего не меняя')
    args = parser.parse_args()

    path = Path(args.config) if args.config else default_config_path()
    remote = get_remote_name(args.remote)
    if not path.is_file():
        sys.exit('Файл не найден: %s' % path)

    if args.check:
        status = check_config(path, remote)
        token = extract_token(path, remote)
        if status == 0 and token:
            status = check_live(token)
        sys.exit(status)
    token = read_token(args.force)
    backup, previous = patch_config(path, remote, token)

    print('Файл:    %s' % path)
    print('Remote:  [%s]' % remote)
    print('Было:    %s' % masked_line(previous))
    print('Стало:   %s' % masked_line(token_line(token)))
    print('Токен:   %s' % masked(token))
    print('Бэкап:   %s' % backup)
    print('Проверка: rclone lsd "%s:"' % remote)


if __name__ == '__main__':
    main()
