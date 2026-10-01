"""Build a highlighted walkthrough from actual Browser screenshots (01..08.jpg)."""
from pathlib import Path
import subprocess
DAY = Path(__file__).resolve().parent
FRAMES = DAY / 'video-frames'
OUTPUT = DAY.parent / 'ChallengeVideos/day24-demo.mp4'
TITLES = ['День 24: проверяем ответ по источникам и цитатам',
          'Шаг 1: прочитайте выделенное утверждение У1 слева',
          'Шаг 2: проверьте source, section и chunk_id в центре',
          'Шаг 3: сравните выделенную цитату справа с утверждением',
          'Шаг 4: проверка наличия источников, цитат и смысла',
          'Все 10 вопросов: источники 10/10, цитаты 10/10, смысл 10/10',
          'Оставшиеся вопросы: все три требования проверены в каждой строке',
          'Релевантность ниже порога: не знаю + просьба уточнить']
DURATIONS = [5, 8, 8, 9, 8, 9, 9, 9]

def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    parts = []
    for i, title in enumerate(TITLES, 1):
        shot = FRAMES / f'{i:02}.jpg'
        if not shot.is_file():
            raise FileNotFoundError(f'Сохраните снимок реального UI: {shot}')
        caption = FRAMES / f'caption-{i}.txt'
        caption.write_text(title, encoding='utf-8')
        segment = FRAMES / f'part-{i}.mp4'
        # ffmpeg runs inside FRAMES so Windows drive colons never enter filter paths.
        font = 'C\\:/Windows/Fonts/segoeui.ttf'
        # Reserve a title strip, so explanations never cover the UI being checked.
        filters = f"scale=1920:1000:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:80,drawbox=x=0:y=0:w=iw:h=70:color=0x030711@0.95:t=fill,drawtext=fontfile='{font}':textfile=caption-{i}.txt:fontcolor=0x6be7a7:fontsize=34:x=(w-tw)/2:y=16,setsar=1"
        subprocess.run(['ffmpeg','-y','-loglevel','error','-loop','1','-i',shot.name,'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-t',str(DURATIONS[i-1]),'-vf',filters,'-r','25','-c:v','libx264','-preset','veryfast','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-shortest',segment.name],cwd=FRAMES,check=True)
        parts.append(f"file '{segment.name}'")
    playlist = FRAMES / 'segments.txt'
    playlist.write_text('\n'.join(parts), encoding='utf-8')
    subprocess.run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',playlist.name,'-c','copy','-movflags','+faststart',str(OUTPUT)],cwd=FRAMES,check=True)
    print(OUTPUT)

if __name__ == '__main__':
    main()
