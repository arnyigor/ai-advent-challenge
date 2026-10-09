"""Build the day 30 demo video from saved real API evidence; no new model calls.

Requires Pillow and ffmpeg in PATH. The story is deliberately short and answers
three questions on every scene: what it is, why it is needed, how it was checked.
Numbers and answers are read from evidence/day30-*.json; the two chat scenes are
real browser screenshots captured by capture-chat.mjs.

    python record_video.py                 # ~1:50, 8 scenes
    python record_video.py --pace 1.0      # longer version of the same scenes
    python record_video.py --pace 0.5      # about 1:30
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FRAMES = ROOT / 'video-frames'
OUT = ROOT.parent / 'ChallengeVideos' / 'day30-demo.mp4'
FONT = Path('C:/Windows/Fonts/segoeui.ttf')
BOLD = Path('C:/Windows/Fonts/segoeuib.ttf')
BG, PANEL, WHITE, MUTED, GREEN = '#0b1220', '#142235', '#eef4ff', '#b8c7db', '#78dec0'

TOTAL = 8
# Scene length multiplier: 1.0 is a slower read, 0.62 is the default speed.
PACE = float(os.environ.get('VIDEO_PACE', '0.62'))


def read(name):
    return json.loads((ROOT / 'evidence' / name).read_text(encoding='utf-8'))


def calls(evidence, prefix=''):
    return [c for c in evidence['calls'] if str(c.get('call', '')).startswith(prefix)]


def one(evidence, prefix, status=None):
    for record in calls(evidence, prefix):
        if status is None or record.get('status') == status:
            return record
    raise LookupError(f'no call {prefix!r} status={status} in {evidence["stage"]}')


def expectation(evidence, prefix):
    for item in evidence['expectations']:
        if item['name'].startswith(prefix):
            return item
    raise LookupError(f'no expectation {prefix!r} in {evidence["stage"]}')


def font(size, bold=False):
    return ImageFont.truetype(str(BOLD if bold else FONT), size)


def wrapped(draw, text, size=34, width=1700, bold=False):
    handle = font(size, bold)
    result = []
    for paragraph in str(text).splitlines():
        line = ''
        for word in paragraph.split():
            candidate = (line + ' ' + word).strip()
            if line and draw.textlength(candidate, font=handle) > width:
                result.append(line)
                line = word
            else:
                line = candidate
        result.append(line)
    return result


def caption_bar(d, caption, footer):
    d.rectangle((0, 892, 1920, 1080), fill='#1a2e43')
    for i, line in enumerate(wrapped(d, caption, 28, 1740)):
        d.text((80, 918 + i * 38), line, font=font(28), fill=WHITE)
    d.text((80, 1038), footer, font=font(20), fill=MUTED)


def slide(number, title, subtitle, blocks, caption, seconds):
    im = Image.new('RGB', (1920, 1080), BG)
    d = ImageDraw.Draw(im)
    d.text((80, 34), 'AI ADVENT  /  ДЕНЬ 30  /  ДОМАШНИЙ AI-СЕРВИС', font=font(24, True), fill=GREEN)
    d.text((80, 88), title, font=font(48, True), fill=WHITE)
    d.text((80, 162), subtitle, font=font(25), fill=MUTED)
    y = 226
    for label, text, size in blocks:
        lines = wrapped(d, text, size, 1680)
        height = 50 + len(lines) * (size + 12) + 20
        if y + height > 882:
            raise ValueError(f'slide {number} overflows: {label}')
        d.rounded_rectangle((65, y, 1855, y + height), radius=18, fill=PANEL)
        d.text((95, y + 12), label, font=font(23, True), fill=GREEN)
        for i, line in enumerate(lines):
            d.text((95, y + 48 + i * (size + 12)), line, font=font(size), fill=WHITE)
        y += height + 14
    caption_bar(d, caption, f'{number:02d} / {TOTAL:02d}    •    титры по сохранённым реальным ответам API')
    path = FRAMES / f'scene-{number:02d}.png'
    im.save(path)
    return dict(title=title, seconds=seconds, file=path.name)


def chat_slide(number, image, crop, title, subtitle, caption, seconds):
    """Scene built from a real browser screenshot of the chat UI."""
    shot = Image.open(ROOT / 'evidence' / image).convert('RGB').crop(crop)
    limit_w, limit_h = 1789, 620
    scale = min(limit_w / shot.width, limit_h / shot.height)
    shot = shot.resize((int(shot.width * scale), int(shot.height * scale)), Image.LANCZOS)
    im = Image.new('RGB', (1920, 1080), BG)
    d = ImageDraw.Draw(im)
    d.text((80, 34), 'AI ADVENT  /  ДЕНЬ 30  /  ДОМАШНИЙ AI-СЕРВИС', font=font(24, True), fill=GREEN)
    d.text((80, 88), title, font=font(48, True), fill=WHITE)
    d.text((80, 162), subtitle, font=font(25), fill=MUTED)
    left = (1920 - shot.width) // 2
    top = 226 + (620 - shot.height) // 2
    d.rectangle((left - 6, top - 6, left + shot.width + 6, top + shot.height + 6), outline='#26374f', width=3)
    im.paste(shot, (left, top))
    caption_bar(d, caption, f'{number:02d} / {TOTAL:02d}    •    снимок браузера: ответы и request_id взяты из DOM')
    path = FRAMES / f'scene-{number:02d}.png'
    im.save(path)
    return dict(title=title, seconds=seconds, file=path.name)


FLOW_CROP = (300, 130, 1620, 950)      # окно чата внутри кадра 1920x1200
FLOW_AREA_H = 656


def flow_scene(number, flow, title, subtitle, caption):
    """Scene made of a real frame sequence of the live chat interaction."""
    flow_dir = FRAMES / 'chatflow'
    out_dir = FRAMES / f'flow-{number:02d}'
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = sorted(flow_dir.glob('f*.jpg'))
    if not frames:
        raise RuntimeError(f'нет кадров в {flow_dir}; сначала запустите: node capture-chat.mjs')
    area_top = 226
    for index, frame in enumerate(frames):
        shot = Image.open(frame).convert('RGB').crop(FLOW_CROP)
        scale = min(1789 / shot.width, FLOW_AREA_H / shot.height)
        shot = shot.resize((int(shot.width * scale), int(shot.height * scale)), Image.LANCZOS)
        im = Image.new('RGB', (1920, 1080), BG)
        d = ImageDraw.Draw(im)
        d.text((80, 34), 'AI ADVENT  /  ДЕНЬ 30  /  ДОМАШНИЙ AI-СЕРВИС', font=font(24, True), fill=GREEN)
        d.text((80, 88), title, font=font(48, True), fill=WHITE)
        d.text((80, 162), subtitle, font=font(25), fill=MUTED)
        left = (1920 - shot.width) // 2
        top = area_top + (FLOW_AREA_H - shot.height) // 2
        d.rectangle((left - 6, top - 6, left + shot.width + 6, top + shot.height + 6), outline='#26374f', width=3)
        im.paste(shot, (left, top))
        caption_bar(d, caption, f'{number:02d} / {TOTAL:02d}    •    кадр {index + 1:02d} из {len(frames)}: живой диалог в реальном времени')
        im.save(out_dir / f'frame-{index:05d}.png')
    seconds = round(len(frames) / flow['fps'], 1)
    return dict(title=title, kind='flow', dir=f'flow-{number:02d}', frames=len(frames),
                fps=flow['fps'], seconds=seconds, file=None)


def main():
    global PACE
    if '--pace' in sys.argv:
        PACE = float(sys.argv[sys.argv.index('--pace') + 1])
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('ffmpeg is required')
    FRAMES.mkdir(exist_ok=True)
    OUT.parent.mkdir(exist_ok=True)

    backend = read('day30-backend.json')
    core = read('day30-core.json')
    budget = read('day30-budget.json')
    context = read('day30-context.json')
    load = read('day30-load.json')
    concurrent = read('day30-concurrent.json')
    queue = read('day30-queue.json')
    ratelimit = read('day30-ratelimit.json')
    network = read('day30-network.json')
    down = read('day30-backend-down.json')
    up = read('day30-backend-up.json')
    summary = read('day30-summary.json')
    chat_ui = read('day30-chat-ui.json')

    scenes = []

    def add(title, subtitle, blocks, caption, seconds):
        scenes.append(slide(len(scenes) + 1, title, subtitle, blocks, caption, max(8, round(seconds * PACE))))

    def add_flow(flow, title, subtitle, caption):
        scenes.append(flow_scene(len(scenes) + 1, flow, title, subtitle, caption))

    props = one(backend, 'backend:/props')
    profile = (f"alias={props['model_alias']} · окно {props['n_ctx']} · слотов {props['total_slots']} · "
               f"CPU 8 потоков · reasoning off")
    chat_turn = one(backend, 'backend:chat')
    bind_health = one(network, 'GET /health')
    bind_ok = expectation(network, 'the bind address still requires a key')['ok']
    direct = one(backend, 'backend: direct calls')
    no_key = one(core, 'GET /v1/models (no key)')
    rl_reject = one(ratelimit, 'ratelimit #11')
    overflow = one(queue, 'queue: overflow request')
    low = one(context, 'context: just below the boundary')
    high = one(context, 'context: above boundary math')
    high_call = one(context, 'context: prompt + answer over')
    load_calls = calls(load, 'load #')
    load_wall = [c['wall_ms'] for c in load_calls]
    truncated = sum(1 for c in load_calls if c.get('finish_reason') == 'length')
    wrong_tag = sum(int(r.get('wrong_tag') or 0) for r in calls(concurrent, 'concurrent round'))
    concurrent_answers = len([c for c in calls(concurrent, 'concurrent r') if 'TAG-' in c['call']])

    add('Зачем этот день', 'домашняя модель — это ещё не сервис', [
        ('ЧТО ЕСТЬ СЕЙЧАС',
         'Qwen3-1.7B Q4_K_M работает на этом компьютере на CPU, но пользоваться им можно только из его собственной программы.', 32),
        ('ЧЕГО ХОЧУ',
         'Спрашивать модель с телефона и ноутбука в домашней сети — и при этом не отдавать промпты в облако.', 32),
        ('ЧТО ДОЛЖЕН УМЕТЬ СЕРВИС',
         'Ключ доступа (пользуются только свои), лимит частоты и очередь (один клиент не занимает модель), '
         'проверка контекста (запрос не падает молча), понятные ошибки вместо 500.', 30),
    ], 'Дальше: как это устроено, что именно проверено на живом сервисе и что честно осталось непроверенным.', 22)

    add('Решение: шлюз между сетью и моделью', 'модель остаётся приватной, наружу смотрит только шлюз', [
        ('СХЕМА',
         'устройство в домашней сети  →  192.168.1.212:8091  (шлюз + веб-чат)  →  127.0.0.1:8081  (модель)', 32),
        ('ЧТО ДЕЛАЕТ ШЛЮЗ',
         'проверяет ключ · считает лимит 10 запросов за 60 с · держит очередь 1 активная + 3 ожидающих · '
         'считает токены контекста · пишет access-лог без промптов и ответов', 27),
        ('ЗАЩИТА В ДВА СЛОЯ',
         f"клиентский ключ на шлюзе и ключ самой модели: её прямые вызовы без ключа — {'HTTP ' + ' · '.join(str(v) for v in direct['statuses'].values())}", 28),
    ], 'Модель слушает только loopback и не выставлена в сеть: снаружи виден лишь шлюз, порт 8090 (Strata) не используется.', 22)

    add('Что именно запущено', 'одна модель, один слот, воспроизводимый запуск', [
        ('ПРОФИЛЬ',
         f"{profile}\nтокены считает токенизатор модели: apply-template + tokenize = {chat_turn['counted_prompt_tokens']}, "
         f"в ответе usage.prompt_tokens = {chat_turn['prompt_tokens']}", 28),
        ('ПОЧЕМУ ТАК',
         'Q4_K_M на CPU выбран в дне 29; один слот и окно 4096 — то, что этот компьютер тянет без ошибок памяти.', 28),
        ('КАК ЗАПУСКАЕТСЯ',
         'run-model.bat (модель на 8081) и run-service.ps1 (шлюз на 8091); обе задачи добавлены в автозапуск Windows.', 28),
    ], f"Готовность шлюза отвечает на LAN-адресе: GET {bind_health['call'].split('via ')[-1]}/health → HTTP {bind_health['status']}.", 20)

    seed_turn, hist_turn = chat_ui['turns'][0], chat_ui['turns'][1]
    add_flow(chat_ui['flow'], 'Как это выглядит: живой чат, реальное время',
             f"браузер печатает вопрос → кнопка «Отправить» → шлюз → модель отвечает "
             f"({chat_ui['flow']['frames']} кадр(ов) за {chat_ui['flow']['elapsed_sec']} с, без ускорения)",
             f"Вопросы набраны по символам в настоящем браузере: «Запомни код КЕДР-42» и «Какой код я просил запомнить?». "
             f"Модель ответила «{seed_turn['answer'].strip()}» и «{hist_turn['answer'].strip()}» — это ответы живого шлюза, "
             f"а в строке под каждым видно время, токены, finish_reason и request_id.")

    add('Ключ: чужой не пройдёт', 'проверка ключа происходит до обращения к модели', [
        ('КЛИЕНТ БЕЗ КЛЮЧА',
         f"без ключа → HTTP {no_key['status']} {no_key['error_code']} · неверный ключ → HTTP "
         f"{one(core, 'GET /v1/models (wrong key)')['status']} {one(core, 'GET /v1/models (wrong key)')['error_code']}", 30),
        ('МОДЕЛЬ НАПРЯМУЮ',
         'llama-server запущен с --api-key: /props, /v1/models и /v1/chat/completions без ключа модели отвечают 401', 28),
        ('ЗАЧЕМ',
         'сервис живёт в домашней сети, но не для всех устройств и не для чужих процессов на этом компьютере.', 29),
    ], 'Неверные ключи не попадают в таблицу лимитов: подбор ключа не расходует ваши 10 запросов в минуту.', 20)

    add('Лимиты: почему сервис не зависает', 'каждый лимит подтверждён реальным ответом API', [
        ('ЧАСТОТА',
         f"11-й запрос за 60 с → HTTP {rl_reject['status']} {rl_reject['error_code']} + Retry-After: {rl_reject['retry_after']} с; "
         f"после окна тот же ключ → HTTP {one(ratelimit, 'ratelimit: after the window')['status']}", 27),
        ('ОЧЕРЕДЬ',
         f"1 генерация + 3 ожидающих; 5-й запрос → HTTP {overflow['status']} {overflow['error_code']} "
         f"+ Retry-After: {overflow['retry_after']} с, после освобождения → HTTP {one(queue, 'queue: recovery request')['status']}", 27),
        ('КОНТЕКСТ И РАЗМЕР ЗАПРОСА',
         f"prompt {high['prompt_tokens']} + 256 + запас 32 > 4096 → HTTP {high_call['status']} context_limit за {high_call['wall_ms']} мс; "
         f"тело > 64 KiB → HTTP {one(core, 'reject: body over 64 KiB')['status']}", 26),
    ], f"Запрос, который помещается, проходит: prompt {low['counted_prompt_tokens']} + 16 + 32 ≤ 4096 → HTTP {low['status']}. История не обрезается молча.", 22)

    add('Проверено на живых запросах', 'не на словах, а на сохранённых отчётах', [
        ('НАГРУЗКА',
         f"{len(load_calls)} последовательных запросов: 200 у всех, медиана {round(statistics.median(load_wall))} мс, "
         f"максимум {max(load_wall)} мс, обрезаний по max_tokens: {truncated}", 28),
        ('ОДНОВРЕМЕННО',
         f"{concurrent_answers} ответов от 3 клиентов в 3 повторах, каждый со своим маркером; перепутанных: {wrong_tag}", 28),
        ('СБОЙ И ВОССТАНОВЛЕНИЕ',
         f"модель остановлена → HTTP {one(down, 'GET /health')['status']} и чат HTTP "
         f"{one(down, 'chat with the model stopped')['status']} {one(down, 'chat with the model stopped')['error_code']}; после запуска → HTTP {one(up, 'chat after restart')['status']}", 27),
    ], f"Всего {summary['total_calls']} реальных вызовов, проваленных ожиданий {summary['failed_expectations']}. "
       f"Одновременный приём — не одновременная генерация: у модели один слот. Обрезание ответа видно как finish_reason={one(budget, 'budget: truncation visible')['finish_reason']}.", 22)

    add('Выводы', 'что это даёт и чего честно не хватает', [
        ('ЧТО ПОЛУЧИЛОСЬ',
         f"приватный AI-сервис на домашнем компьютере: модель на 8081 (только loopback), шлюз и веб-чат на 8091 "
         f"в домашней сети, автозапуск двумя задачами, 34 юнит-теста и {summary['total_calls']} проверочных вызова", 27),
        ('ЧТО ЭТО ДАЁТ',
         'спрашивать модель с любого устройства в доме; промпты и ответы не уходят в облако; ключ, лимит частоты, '
         'очередь и проверка контекста не дают одному клиенту занять модель; ошибки внятные — 401, 400, 413, 429, 503', 26),
        ('ЧЕГО НЕ ХВАТАЕТ',
         'не проверено со второго устройства и правило firewall (нужны права администратора); нет TLS — ключ по HTTP '
         'в домашней сети не шифруется; перезагрузка ОС не проверялась; качество ответов ограничено маленькой моделью', 26),
    ], 'Итог: сервис работает и проверен реальными запросами; слабые места перечислены прямо, а не спрятаны. Код и доказательства — README.md, evidence/*.json, PLAN.md, DEMO.md.', 22)

    elapsed = 0
    for index, scene in enumerate(scenes, 1):
        scene['at'] = elapsed
        elapsed += scene['seconds']
        print(f"scene {index}/{len(scenes)}: {scene['title']} ({scene['seconds']}s)", flush=True)
        if scene.get('kind') == 'flow':
            source = ['-framerate', str(scene['fps']), '-i', str(FRAMES / scene['dir'] / 'frame-%05d.png')]
        else:
            source = ['-loop', '1', '-i', str(FRAMES / scene['file'])]
        subprocess.run([ffmpeg, '-y', '-loglevel', 'error', *source, '-t', str(scene['seconds']), '-r', '25',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                        str(FRAMES / f'segment-{index:02d}.mp4')], check=True)
    (FRAMES / 'segments.txt').write_text(
        '\n'.join(f"file 'segment-{i:02d}.mp4'" for i in range(1, len(scenes) + 1)), encoding='utf-8')
    subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                    '-i', str(FRAMES / 'segments.txt'), '-c', 'copy', '-movflags', '+faststart', str(OUT)], check=True)
    (FRAMES / 'manifest.json').write_text(json.dumps({'seconds': elapsed, 'scenes': scenes}, ensure_ascii=False, indent=2),
                                          encoding='utf-8')
    print(f'{OUT} ({elapsed}s)', flush=True)



if __name__ == '__main__':
    main()
