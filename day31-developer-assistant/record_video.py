"""Captioned demo built from real browser screenshots; waiting is shortened."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

DAY = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DAY.parent / 'ChallengeVideos' / 'day31-demo.mp4')
    args = parser.parse_args()
    ffmpeg = os.environ.get('FFMPEG_PATH') or shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Set FFMPEG_PATH or install ffmpeg')
    report = json.loads((DAY / 'evidence' / 'browser-demo.json').read_text(encoding='utf-8'))
    font_path = Path(os.environ.get('DAY31_VIDEO_FONT', str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf')))
    large, small = ImageFont.truetype(str(font_path), 48), ImageFont.truetype(str(font_path), 27)
    frames = DAY / 'video-frames'
    frames.mkdir(exist_ok=True)
    args.output.parent.mkdir(exist_ok=True)

    def card(name, title, lines):
        frame = Image.new('RGB', (1920,1080), '#0c1322')
        draw = ImageDraw.Draw(frame)
        draw.text((100,110),'AI ADVENT / ДЕНЬ 31',font=small,fill='#78dfc4')
        draw.text((100,190),title,font=large,fill='#edf3ff')
        for i,line in enumerate(lines):
            draw.text((100,320+i*78),line,font=small,fill='#cedcf1')
        target=frames / name
        frame.save(target)
        return target

    first = report['turns'][0]
    start = card('title.png','Ассистент разработчика: RAG + MCP + /help',[
        'README + docs → E5 embeddings → SQLite vector + FTS5 → найденные фрагменты',
        'MCP stdio → текущая git-ветка и HEAD → контекст проекта',
        'Локальная LLM → ответ с источниками и видимыми ограничениями',
        'Далее — настоящие снимки браузера и реальные ответы модели.',
        'Монтаж: ожидание генерации сокращено. Озвучки нет.',
    ])
    end = card('result.png','Что подтверждено',[
        '35 документов · README + docs · реальная E5 multilingual-e5-small',
        'MCP: initialize → tools/list → tools/call; ветка совпадает с Git',
        '20 тестов: команда, индекс, HTTP, MCP, смена ветки, область поиска',
        'Ответы о структуре и API с источниками; отказ на неизвестную выручку',
        f"Модель: {first['model']}; история диалога не передаётся",
        'Номера ссылок проверяются; смысловую точность нужно сверять с документами.',
    ])
    scenes=[(start,12,''),
        (DAY/'evidence/ui-00-ready.png',12,'Корпус: корневой README, README дней и настоящая папка docs/.'),
        (DAY/'evidence/ui-01-pending.png',4,'Запрос отправлен через форму. Ожидание генерации в монтаже сокращено.'),
        (DAY/'evidence/ui-2-answer.png',25,'/help объясняет структуру проекта; ссылки [n] ведут к фрагментам ниже.'),
        (DAY/'evidence/ui-source.png',18,'RAG: оригинальный фрагмент docs/architecture.md подтверждает расположение компонентов.'),
        (DAY/'evidence/ui-mcp.png',20,'MCP: настоящий каталог, get_project_context({}), текущая ветка и SHA HEAD.'),
        (DAY/'evidence/ui-3-answer.png',25,'Вопрос об API: модель использует контракт docs/api.md.'),
        (DAY/'evidence/ui-4-answer.png',12,'Живая ветка приходит из MCP при каждом запросе, а не из RAG.'),
        (DAY/'evidence/ui-5-answer.png',14,'В документации нет выручки. Помощник сообщает недостаток данных.'),
        (end,14,'')]
    manifest=[]
    for index,(source,duration,caption) in enumerate(scenes):
        frame=Image.open(source).convert('RGB').resize((1920,1080))
        if caption:
            draw=ImageDraw.Draw(frame)
            draw.rectangle((0,990,1920,1080),fill='#0c1322')
            draw.text((38,1018),caption,font=small,fill='#edf3ff')
        target=frames / f'scene-{index:02d}.png'
        frame.save(target)
        manifest.append((target,duration))
    concat=frames/'concat.txt'
    concat.write_text(''.join(f"file '{p.as_posix()}'\nduration {n}\n" for p,n in manifest)+f"file '{manifest[-1][0].as_posix()}'\n",encoding='utf-8')
    subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(concat),
        '-t',str(sum(duration for _,duration in manifest)),
        '-vf','fps=25','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(args.output)],check=True)
    print(args.output.resolve())


if __name__ == '__main__':
    main()
