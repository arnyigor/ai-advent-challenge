"""Encode continuous browser frames using real timestamps, no staged answers."""
import json
from pathlib import Path
import shutil
import subprocess

DAY = Path(__file__).resolve().parent


def main():
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('ffmpeg and ffprobe required')
    recording = json.loads((DAY / 'evidence/live-browser.json').read_text(encoding='utf-8'))
    frames = recording['frames']
    if len(frames) < 2 or len(recording['answers']) != 3:
        raise ValueError('Complete continuous browser capture required')
    concat = Path(frames[0]['file']).parent / 'concat.txt'
    lines = []
    for i, frame in enumerate(frames):
        duration = (frames[i+1]['timestamp']-frame['timestamp'])/1000 if i+1 < len(frames) else .25
        lines += ["file '" + Path(frame['file']).as_posix() + "'", f'duration {duration:.3f}']
    lines += ["file '" + Path(frames[-1]['file']).as_posix() + "'"]
    concat.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    output = DAY.parent / 'ChallengeVideos/day33-demo.mp4'
    output.parent.mkdir(exist_ok=True)
    subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
        '-i', str(concat), '-vf', 'fps=25', '-c:v', 'libx264', '-preset', 'fast', '-crf', '21',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)], check=True)
    info = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_format', '-show_streams',
        '-of', 'json', str(output)], text=True))
    (DAY / 'evidence/video.json').write_text(json.dumps({'video': str(output),
        'frames': len(frames), 'kind': recording['kind'], 'probe': info}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
