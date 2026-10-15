"""Encode every frame of a real browser run; accelerate only labelled idle waits."""
import json
from pathlib import Path
import shutil
import subprocess

DAY = Path(__file__).resolve().parent


def main():
    recording = json.loads((DAY / 'evidence/live-browser.json').read_text(encoding='utf-8'))
    frames = recording['frames']
    if recording['run']['status'] != 'done' or len(frames) < 2:
        raise ValueError('Successful real browser run required')
    lines, encoded_duration = [], 0
    for i, frame in enumerate(frames):
        dt = (frames[i+1]['timestamp'] - frame['timestamp']) / 1000 if i+1 < len(frames) else .4
        duration = max(.02, dt / frame.get('speed', 1))
        encoded_duration += duration
        lines += ["file '" + Path(frame['file']).as_posix().replace("'", "'\\''") + "'", f'duration {duration:.5f}']
    lines += ["file '" + Path(frames[-1]['file']).as_posix() + "'"]
    concat = Path(frames[0]['file']).parent / 'concat.txt'
    concat.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    output = DAY.parent / 'ChallengeVideos/day34-demo.mp4'
    if output.exists() and not output.with_name('day34-captioned-slides.mp4').exists():
        shutil.copy2(output, output.with_name('day34-captioned-slides.mp4'))
    subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'concat', '-safe', '0', '-i', str(concat), '-vf', 'fps=25',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(output)], check=True)
    probe = json.loads(subprocess.check_output([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
        '-show_format', '-show_streams', '-of', 'json', str(output)], text=True))
    report = {'video': str(output), 'kind': recording['kind'], 'frames': len(frames),
        'raw_duration_sec': (frames[-1]['timestamp']-frames[0]['timestamp'])/1000,
        'encoded_duration_sec': encoded_duration, 'probe': probe}
    (DAY / 'evidence/live-video.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
