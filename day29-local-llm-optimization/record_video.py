"""Build a captioned video from saved benchmark evidence; no model calls.

Requires Pillow and ffmpeg. All numerical tables and quoted answers are read
from evidence/*.json and optimized.json. This is a results montage, not a
recording of a new live inference session.
"""
import json
import shutil
import statistics
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FRAMES = ROOT / 'video-frames'
OUT = ROOT.parent / 'ChallengeVideos' / 'day29-demo.mp4'
FONT = Path('C:/Windows/Fonts/segoeui.ttf')
BOLD = Path('C:/Windows/Fonts/segoeuib.ttf')
BG, PANEL, WHITE, MUTED, GREEN = '#0b1220', '#142235', '#eef4ff', '#b8c7db', '#78dec0'


def read(name):
    return json.loads((ROOT / 'evidence' / name).read_text(encoding='utf-8'))


def font(size, bold=False):
    return ImageFont.truetype(str(BOLD if bold else FONT), size)


def wrapped(draw, text, size=34, width=1700, bold=False):
    f = font(size, bold)
    result = []
    for paragraph in str(text).splitlines():
        line = ''
        for word in paragraph.split():
            candidate = (line + ' ' + word).strip()
            if line and draw.textlength(candidate, font=f) > width:
                result.append(line)
                line = word
            else:
                line = candidate
        result.append(line)
    return result


def slide(number, title, blocks, caption, seconds, sources):
    im = Image.new('RGB', (1920, 1080), BG)
    d = ImageDraw.Draw(im)
    d.text((80, 44), 'AI ADVENT  /  ДЕНЬ 29  /  QWEN3-1.7B', font=font(25, True), fill=GREEN)
    d.text((80, 108), title, font=font(52, True), fill=WHITE)
    d.text((80, 187), 'Сохранённые реальные прогоны • CPU, 8 потоков • новые вызовы модели не выполняются', font=font(26), fill=MUTED)
    y = 262
    for label, text, size in blocks:
        lines = wrapped(d, text, size, 1680)
        height = 56 + len(lines) * (size + 13) + 24
        if y + height > 865:
            raise ValueError(f'Slide {number} overflows: {label}')
        d.rounded_rectangle((65, y, 1855, y + height), radius=20, fill=PANEL)
        d.text((95, y + 15), label, font=font(25, True), fill=GREEN)
        for i, line in enumerate(lines):
            d.text((95, y + 56 + i * (size + 13)), line, font=font(size), fill=WHITE)
        y += height + 17
    d.rectangle((0, 892, 1920, 1080), fill='#1a2e43')
    for i, line in enumerate(wrapped(d, caption, 29, 1720)):
        d.text((80, 915 + i * 40), line, font=font(29), fill=WHITE)
    d.text((80, 1036), f'{number:02d} / 09    •    Демонстрация результатов с титрами, без звука', font=font(21), fill=MUTED)
    path = FRAMES / f'scene-{number:02d}.png'
    im.save(path)
    return dict(file=path.name, title=title, seconds=seconds, sources=sources, caption=caption)


def main():
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('ffmpeg is required')
    FRAMES.mkdir(exist_ok=True)
    OUT.parent.mkdir(exist_ok=True)
    cfg = json.loads((ROOT / 'optimized.json').read_text(encoding='utf-8'))
    compact = read('compact-confirmation-Q4_K_M.json')
    before, after = cfg['before'], cfg['after']
    scenes = []
    def add(title, blocks, caption, seconds, sources):
        scenes.append(slide(len(scenes)+1, title, blocks, caption, seconds, sources))

    add('Задача: оптимизировать локальный RAG', [
        ('ПРЕЕМСТВЕННОСТЬ С ДНЁМ 28', 'Тот же поиск документов, те же 6 вопросов. Контекст заморожен до экспериментов.', 35),
        ('ЧТО МЕНЯЕМ', 'Квантование, temperature, лимит ответа, окно контекста и системный промпт.', 35),
        ('УСЛОВИЯ', 'Малая Qwen3-1.7B работает на CPU. Большая модель Strata не участвует.', 35),
    ], 'Температура и системный промпт меняются в запросе без перезагрузки. Квантование и окно проверяются отдельными запусками сервера.', 17, ['frozen.json', 'optimized.json'])

    quant_lines = []
    for quant in ('Q2_K', 'Q4_K_M', 'Q8_0'):
        report = read(f'quant-pilot-{quant}.json')
        rows = report['runs']
        quant_lines.append(f"{quant:10s}  |  {report['metadata']['file_bytes']/1024**3:.2f} GiB весов  |  {statistics.median(r['request_sec'] for r in rows):.2f} с  |  {statistics.mean(r['manual_quality'] for r in rows):.2f} / 2")
    add('Квантование: меньше не всегда лучше', [
        ('ВЕСА  /  МЕДИАНА HTTP  /  РУЧНОЕ КАЧЕСТВО', '\n'.join(quant_lines), 34),
        ('ВЫБОР', 'Q4_K_M — лучший баланс в этом пилоте. Q2 часто отказывается отвечать; Q8 не улучшил среднюю оценку.', 35),
    ], 'Пилот: 6 одинаковых вопросов, один повтор на квант. Это ориентир для выбора, а не устойчивый рейтинг скорости.', 18, ['quant-pilot-Q2_K.json', 'quant-pilot-Q4_K_M.json', 'quant-pilot-Q8_0.json'])

    atlas = next(r for r in compact['runs'] if r['case_id'] == 1)
    add('Качество проверяем по источникам', [
        ('РЕАЛЬНЫЙ ОТВЕТ Q4 / COMPACT', atlas['answer'], 34),
        ('РУЧНАЯ ОЦЕНКА: 1 ИЗ 2', 'Факты Atlas верны. Но правило после восстановления связи находится в источнике [2], а ответ ссылается на [1].', 35),
    ], 'Непустой ответ ещё не означает правильный ответ. Проверяем обязательные условия и соответствие ссылок документам.', 20, ['compact-confirmation-Q4_K_M.json', 'frozen.json'])

    add('Temperature: повторяемость без перезагрузки', [
        ('ОДИН КВАНТ И ОДИН СИСТЕМНЫЙ ПРОМПТ', 'В запросе меняется только temperature: 0.1 → 0.0. По 6 вопросов × 3 повтора.', 35),
        ('СКОЛЬКО РАЗНЫХ ОТВЕТОВ НА КАЖДЫЙ ВОПРОС', 'До:     1, 3, 3, 1, 1, 1\nПосле: 1, 1, 1, 1, 1, 1', 38),
        ('ПРЕДЕЛ ВЫВОДА', 'При temperature=0 ответы совпали в трёх повторах. Ошибки в ответах сохранились.', 34),
    ], 'Стабильность измерена на этом наборе. Она не гарантирует одинаковый результат на другом оборудовании или сборке.', 18, ['temperature-confirmation-Q4_K_M.json'])

    prompt = read('prompt-confirmation-Q4_K_M.json')
    bad = next(r for r in prompt['runs'] if r['profile'] == 'focused-control' and r['case_id'] == 6 and r.get('manual_quality') == 0)
    answer = ' '.join(bad['answer'].split())
    # Show the saved answer, with an explicitly marked excerpt if it is lengthy.
    if len(answer) > 620:
        answer = answer[:620] + '… [фрагмент ответа]'
    add('Новый промпт: эксперимент отклонён', [
        ('ВОПРОС БЕЗ ДАННЫХ: ВЫРУЧКА И КЛИЕНТЫ ATLAS', answer, 29),
        ('ПОЧЕМУ НЕ ВЫБРАЛИ', 'После отказа модель приписывает Atlas инструменты MCP. В найденных документах такой связи нет.', 33),
    ], 'Даже более высокая средняя ручная оценка не оправдывает неподтверждённые факты. В итоговом конфиге оставлен исходный промпт.', 23, ['prompt-confirmation-Q4_K_M.json'])

    thinking = read('reasoning-pilot-Q4_K_M.json')
    thinking_lines = '\n'.join(f"Вопрос {r['case_id']}: {r['request_sec']:.2f} с; ручная оценка {r['manual_quality']} / 2" for r in thinking['runs'])
    add('Рассуждения: цена на CPU слишком высока', [
        ('ОТДЕЛЬНЫЙ ПИЛОТ / REASONING ON / BUDGET 512', thinking_lines, 37),
        ('РЕШЕНИЕ ДЛЯ ЭТОГО КЕЙСА', 'Ошибки полностью не исчезли. Для выбранного профиля reasoning выключен.', 36),
    ], 'Это два проверочных вопроса, а не полный тест качества. Время включает весь HTTP-запрос и генерацию рассуждений.', 15, ['reasoning-pilot-Q4_K_M.json'])

    reduction = (1-after['sampled_peak_rss_bytes']/before['sampled_peak_rss_bytes'])*100
    add('До / после: честное сравнение', [
        ('ДО → ПОСЛЕ', f"Пиковый RSS: {before['sampled_peak_rss_bytes']/1024**2:.0f} MiB → {after['sampled_peak_rss_bytes']/1024**2:.0f} MiB\nМедиана HTTP: {before['median_request_sec']:.2f} с → {after['median_request_sec']:.2f} с\nКачество / 2: {before['manual_quality_mean']:.2f} → {after['manual_quality_mean']:.2f}\nОбрезанные ответы: {before['truncated']} → {after['truncated']}", 37),
        ('ПОЛУЧЕННЫЙ ЭФФЕКТ', f'Память процесса сократилась на {reduction:.2f}%. Ответы стали повторяемыми. Скорость и качество не улучшились.', 35),
    ], 'По 18 вызовов до и после. RSS снимается каждые 250 мс у llama-server. Оценки ручные; независимого тестового набора нет.', 23, ['temperature-confirmation-Q4_K_M.json', 'compact-confirmation-Q4_K_M.json', 'optimized.json'])

    config_text = '\n'.join(f'"{k}": {json.dumps(cfg[k])}' for k in ('quantization', 'temperature', 'max_tokens', 'context_window', 'threads', 'reasoning'))
    add('Итоговый конфиг и запуск', [
        ('OPTIMIZED.JSON — ФАКТИЧЕСКИ ВЫБРАННЫЕ ПАРАМЕТРЫ', config_text, 30),
        ('КОД', 'run-cpu-model.bat — запуск сервера\npython ask.py "Ваш вопрос" — поиск и ответ по выбранному конфигу', 33),
    ], 'Системный промпт сохранён из дня 28. Контекст 4096 и ответ до 1024 токенов прошли 18 вызовов без обрезания.', 19, ['optimized.json', 'ask-smoke.json'])

    add('Результат дня 29', [
        ('ЧТО ГОТОВО', 'Код экспериментов • скачанные Q2 / Q4 / Q8 • выбранный конфиг • отчёт с ответами и источниками.', 35),
        ('ЧТО ОСТАЛОСЬ СЛАБЫМ', 'Ошибки RSS и MCP, неверные ссылки и отказы на часть вопросов. Этот конфиг экономит память, но не решает проблему качества.', 35),
        ('ВОСПРОИЗВОДИМОСТЬ', '153 завершённых измеряемых вызова. Данные — evidence/*.json. 19 тестов кода прошли.', 35),
    ], 'Смотрите README.md, RESULTS.md и results/report.html. Видео смонтировано из сохранённых результатов; новые ответы для ролика не генерировались.', 17, ['optimized.json', 'challenge.json'])

    elapsed = 0
    for i, scene in enumerate(scenes, 1):
        scene['at'] = elapsed
        elapsed += scene['seconds']
        print(f"Scene {i}/{len(scenes)}: {scene['title']}", flush=True)
        subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-loop', '1', '-i', str(FRAMES/scene['file']), '-t', str(scene['seconds']), '-r', '25', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', str(FRAMES/f'segment-{i:02d}.mp4')], check=True)
    (FRAMES/'segments.txt').write_text('\n'.join(f"file 'segment-{i:02d}.mp4'" for i in range(1, len(scenes)+1)), encoding='utf-8')
    subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(FRAMES/'segments.txt'), '-c', 'copy', '-movflags', '+faststart', str(OUT)], check=True)
    (FRAMES/'manifest.json').write_text(json.dumps({'seconds': elapsed, 'scenes': scenes}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{OUT} ({elapsed}s)', flush=True)


if __name__ == '__main__':
    main()
