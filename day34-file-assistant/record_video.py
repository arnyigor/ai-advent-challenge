"""Монтаж видео дня 34 из реальных кадров браузера.

Если есть evidence/narration-generation.json (озвучка QwenTTS через ComfyUI) —
каждая сцена длится по факту своего аудио и звук вкладывается в видео.
Иначе собирается версия с текстовыми подписями сцен без звука; длительность
сцены вычисляется из объёма текста. Кадры никогда не перерисовываются:
используются настоящие снимки evidence/short-*.png.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

DAY = Path(__file__).resolve().parent


def find_tool(name):
    path = os.environ.get('FFMPEG_PATH' if name == 'ffmpeg' else 'FFPROBE_PATH') or shutil.which(name)
    if path:
        return path
    candidate = Path(r'G:\AIModels\ComfyUI') / (name + '.exe')
    return str(candidate) if candidate.exists() else None


def wrap(draw, text, font, width):
    lines, current = [], ''
    for word in text.split():
        trial = (current + ' ' + word).strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=DAY.parent / 'ChallengeVideos' / 'day34-demo.mp4')
    args = parser.parse_args()
    ffmpeg = find_tool('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('ffmpeg не найден (PATH, FFMPEG_PATH или G:/AIModels/ComfyUI)')
    narration_path = DAY / 'evidence' / 'narration-generation.json'
    voiced = narration_path.exists()
    ffprobe = find_tool('ffprobe')
    if voiced and not ffprobe:
        raise RuntimeError('для озвученной версии нужен ffprobe')
    narration = json.loads(narration_path.read_text(encoding='utf-8')) if voiced else \
        json.loads((DAY / 'narration.json').read_text(encoding='utf-8'))
    demo = json.loads((DAY / 'evidence' / 'browser-demo.json').read_text(encoding='utf-8'))
    if demo['run']['status'] != 'done':
        raise ValueError('browser-demo.json содержит незавершённый прогон')

    frames = DAY / 'video-frames' / 'short'
    frames.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(exist_ok=True)
    fontpath = os.environ.get('DAY34_VIDEO_FONT',
        str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/segoeui.ttf'))
    titlefont = ImageFont.truetype(fontpath, 44)
    bodyfont = ImageFont.truetype(fontpath, 30)
    captionfont = ImageFont.truetype(fontpath, 27)
    smallfont = ImageFont.truetype(fontpath, 21)

    parts, manifest = [], []
    for i, scene in enumerate(narration['scenes']):
        frame = Image.new('RGB', (1920, 1080), '#0c1322')
        draw = ImageDraw.Draw(frame)
        draw.text((70, 36), scene['title'], font=titlefont, fill='#edf3ff')
        if scene['image'] == 'intro':
            draw.text((90, 190), 'Ассистент сам работает с файлами проекта', font=titlefont, fill='#78dfc4')
            for j, line in enumerate(['читает файлы и ищет по нескольким сразу',
                                      'анализирует и изменяет через инструменты MCP',
                                      'цель на уровне задачи, не «открой файл X»',
                                      'изменения сохраняются и видны как diff']):
                draw.rounded_rectangle((90, 320 + j*135, 1830, 420 + j*135), radius=18, fill='#142238')
                draw.text((125, 350 + j*135), line, font=titlefont, fill='#edf3ff')
        else:
            source = DAY / 'evidence' / scene['image']
            picture = Image.open(source).convert('RGB')
            ratio = min(1700 / picture.width, 700 / picture.height, 1.6)
            picture = picture.resize((round(picture.width*ratio), round(picture.height*ratio)))
            frame.paste(picture, ((1920 - picture.width)//2, 130 + (700 - picture.height)//2))
        caption = draw.textbbox((0, 0), 'A', font=captionfont)[3]
        words = wrap(draw, scene['text'], captionfont, 1500)
        y = 870
        draw.rounded_rectangle((70, y - 14, 1850, min(1052, y + 14 + len(words)*(caption + 10))),
                               radius=14, fill='#101c30')
        for line in words[:3]:
            draw.text((100, y), line, font=captionfont, fill='#cfe3ff')
            y += caption + 10
        footer = 'Реальные кадры браузера · ожидание модели сокращено'
        footer += ' · озвучка QwenTTS Voice Design' if voiced else ' · версия с подписями без озвучки'
        draw.text((70, 1035), footer, font=smallfont, fill='#7e93b3')
        image_path = frames / f'{i:02d}-{scene["id"]}.png'
        frame.save(image_path)
        part = frames / f'{i:02d}.mp4'
        if voiced:
            audio = scene['audio']
            duration = float(subprocess.check_output([ffprobe, '-v', 'error', '-show_entries',
                'format=duration', '-of', 'csv=p=0', audio], text=True)) + .35
            subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-loop', '1',
                '-i', str(image_path), '-i', audio, '-t', str(duration), '-vf', 'fps=25',
                '-af', 'apad,alimiter=limit=0.95', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-b:a', '160k',
                str(part)], check=True)
        else:
            duration = min(16.0, 4.0 + 0.055 * len(scene['text']))
            subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-loop', '1',
                '-i', str(image_path), '-t', str(duration), '-vf', 'fps=25',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
                str(part)], check=True)
        parts.append(part)
        manifest.append({'id': scene['id'], 'duration_sec': duration, 'frame': str(image_path),
                         'audio': scene.get('audio')})
    concat = frames / 'concat.txt'
    concat.write_text(''.join(f"file '{p.as_posix()}'\n" for p in parts), encoding='utf-8')
    subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
        '-i', str(concat), '-c', 'copy', '-movflags', '+faststart', str(args.output)], check=True)
    (DAY / 'evidence' / 'video-scenes.json').write_text(json.dumps(
        {'video': str(args.output.resolve()), 'voiced': voiced, 'model': demo['run'].get('model'),
         'scenes': manifest}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
