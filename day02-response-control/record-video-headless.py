# record-video-headless.py — запись демо-видео Day 02 без видимого окна
#
# Та же архитектура, что у day 01 (record-video.mjs):
#   фоновая «камера» (кадр каждые 125 мс, 8 fps) + ffmpeg собирает mp4.
# Отличие: day 02 — консольное приложение, поэтому «камера» рендерит
# экран терминала (Pillow) по stdout запущенного day2_response_control.py.
# Реальное сценарное взаимодействие: два нажатия Enter по текстам скрипта,
# реальные вызовы Gemini API.
#
# Запуск:
#   python record-video-headless.py                     # → video/day2-demo.mp4
#   python record-video-headless.py --out video/x.mp4
#
# Требования: ffmpeg в PATH (или FFMPEG_PATH), GEMINI_API_KEY в окружении,
# Pillow. Шрифт — Consolas (стандартный для Windows; переопределить FONT_PATH).

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

__file_dir = Path(__file__).resolve().parent

# --- параметры (по аналогии с record-video.mjs из day 01) ---
FPS = 8
CAPTURE_MS = 125
HOLD_BEFORE_ENTER_S = 2.5   # держим экран перед нажатием Enter
FINAL_HOLD_S = 2.5          # держим финальный экран после завершения
COLS = 72
ROWS = 36
FONT_SIZE = 20
MARGIN = 16
CAPTION_H = 52          # высота полосы субтитров внизу кадра
CAPTION_BG = (18, 22, 30)
CAPTION_FG = (255, 241, 115)
ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")

# Субтитры: фаза определялась по тексту на экране (от поздних к ранним маркерам).
CAPTIONS = [
    ("RESULT:", "Controlled: формат соблюдён, длина ограничена, stop marker не возвращён"),
    ("FINAL COMPARISON", "Сравниваем одинаковый запрос при разном контроле output"),
    ("[B] — CONTROLLED", "B: format + ≤100 слов + maxOutputTokens + stopSequence"),
    ("[A] — BASELINE", "A: baseline — без контроля формата, длины и завершения"),
    ("Press Enter to run comparison", "Реальные запросы к Gemini API"),
    ("BASE QUESTION", "Один и тот же содержательный запрос для обоих вызовов"),
]
DEFAULT_CAPTION = "Day 02 — один вопрос, два уровня контроля"

# --- аргументы ---
args = sys.argv[1:]
out_arg = "out"
OUT = str(__file_dir / "video" / "day2-demo.mp4")
for i, a in enumerate(args):
    if a == "--out" and i + 1 < len(args):
        OUT = args[i + 1]
FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
FONT_CANDIDATES = [
    os.environ.get("FONT_PATH", ""),
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\lucconsa.ttf",
]
FRAMES_DIR = Path(OUT).parent / "frames"

# цвета терминала (классическая палитра)
C_DEFAULT = (212, 218, 224)
C_BG = (10, 10, 14)
ANSI_COLORS = {
    "31": (255, 85, 85),     # red
    "32": (121, 255, 140),   # green
    "33": (255, 241, 115),   # yellow
    "36": (0, 229, 255),     # cyan
}


def parse_runs(line):
    """Разбирает строку на сегменты (text, color) по ANSI-кодам."""
    runs = []
    color = C_DEFAULT
    pos = 0
    for m in ANSI_RE.finditer(line):
        if m.start() > pos:
            runs.append((line[pos:m.start()], color))
        code = m.group(1)
        if code == "" or code == "0":
            color = C_DEFAULT
        else:
            color = ANSI_COLORS.get(code, color)
        pos = m.end()
    if pos < len(line):
        runs.append((line[pos:], color))
    return runs


class Screen:
    """Модель экрана: последние ROWS-1 строк, каждая — список сегментов."""

    def __init__(self):
        self.lock = threading.Lock()
        self.lines = []          # список list[(text, color)]
        self.buf = ""            # частичная строка (input() печатает без \n)

    def feed(self, chunk):
        with self.lock:
            self.buf += chunk
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                line = line.rstrip("\r")
                if line == "":
                    self.lines.append([])
                else:
                    self.lines.append(parse_runs(line))
                if len(self.lines) > ROWS - 1:
                    del self.lines[0]

    def snapshot(self):
        with self.lock:
            lines = [list(l) for l in self.lines]
            tail = self.buf
        return lines, tail


def load_font():
    for p in FONT_CANDIDATES:
        if p and os.path.isfile(p):
            return ImageFont.truetype(p, FONT_SIZE)
    raise SystemExit("Consolas не найден — укажите FONT_PATH")


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY не задан в окружении")
    font = load_font()
    cw = font.getlength("a")
    lh = FONT_SIZE + 8
    W = int(cw * COLS + 2 * MARGIN)
    H = int(lh * ROWS + 2 * MARGIN + CAPTION_H)
    W, H = W + (W % 2), H + (H % 2)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for old in FRAMES_DIR.glob("f*.png"):
        old.unlink()

    screen = Screen()
    create_no_window = 0x08000000 if os.name == "nt" else 0
    # interactive-режим: рекордер сам жмёт Enter по сценарию.
    # Модель для финального видео фиксируем быстрой low-latency flash-lite,
    # чтобы на ролике не было длинных ожиданий и fallback.
    script_args = ["--model", "gemini-3.5-flash-lite"]
    for i, a in enumerate(args):
        if a == "--model" and i + 1 < len(args):
            script_args += ["--model", args[i + 1]]
    proc = subprocess.Popen(
        [sys.executable, "-u", str(__file_dir / "day2_response_control.py")] + script_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(__file_dir),
        creationflags=create_no_window,
    )

    def reader():
        dec = __import__("codecs").getincrementaldecoder("utf-8")("replace")
        while True:
            chunk = proc.stdout.read1(4096)  # read1: возвращает доступные байты сразу, не ждёт буфер 4096
            if not chunk:
                break
            screen.feed(dec.decode(chunk, True))
        screen.feed(dec.decode(b"", True))

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    def current_caption():
        lines, tail = screen.snapshot()
        text = "\n".join("".join(seg[0] for seg in line) for line in lines) + tail
        for marker, caption in CAPTIONS:
            if marker in text:
                return caption
        return DEFAULT_CAPTION

    def render(path):
        img = Image.new("RGB", (W, H), C_BG)
        d = ImageDraw.Draw(img)
        term_h = H - CAPTION_H
        lines, tail = screen.snapshot()
        y = term_h - MARGIN - lh * len(lines)
        for runs in lines:
            x = MARGIN
            for text, color in runs:
                d.text((x, y), text, font=font, fill=color)
                x += font.getlength(text)
            y += lh
        if tail:
            x = MARGIN
            for text, color in parse_runs(tail):
                d.text((x, y), text, font=font, fill=color)
                x += font.getlength(text)
        # полоса субтитров внизу кадра
        d.rectangle([0, H - CAPTION_H, W, H], fill=CAPTION_BG)
        d.line([0, H - CAPTION_H, W, H - CAPTION_H], fill=(60, 66, 80))
        caption = current_caption()
        cx = max(0, (W - font.getlength(caption)) / 2)
        cy = H - CAPTION_H + (CAPTION_H - FONT_SIZE) // 2
        d.text((cx, cy), caption, font=font, fill=CAPTION_FG)
        img.save(path)

    print(f"-> Снимаю: {OUT} ({W}x{H}, {FPS} fps)")
    frame_idx = 0
    next_frame = time.monotonic()
    enter1_at = enter2_at = None
    sent1 = sent2 = False
    proc_alive = True
    alive_done = False

    while True:
        now = time.monotonic()
        # сценарий: два Enters по текстам скрипта
        _, tail = screen.snapshot()
        if not sent2 and "Press Enter to run comparison" in tail:
            if enter2_at is None:
                enter2_at = now
            elif now - enter2_at >= HOLD_BEFORE_ENTER_S:
                proc.stdin.write(b"\n")
                proc.stdin.flush()
                sent2 = True
        elif not sent1 and "Press Enter to run" in tail:
            if enter1_at is None:
                enter1_at = now
            elif now - enter1_at >= HOLD_BEFORE_ENTER_S:
                proc.stdin.write(b"\n")
                proc.stdin.flush()
                sent1 = True
        if not alive_done and proc.poll() is not None:
            proc_alive = False
            alive_done = True
            exit_at = now
        if not proc_alive and now - exit_at >= FINAL_HOLD_S:
            break
        if now >= next_frame:
            render(FRAMES_DIR / f"f{frame_idx:04d}.png")
            frame_idx += 1
            next_frame += CAPTURE_MS / 1000.0

    render(FRAMES_DIR / f"f{frame_idx:04d}.png")
    frame_idx += 1
    proc.wait()
    t.join(timeout=5)
    print(f"-> Кадров: {frame_idx}")

    out = Path(OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    print("-> Собираю mp4...")
    cmd = (
        f'"{FFMPEG}" -y -framerate {FPS} -i "{FRAMES_DIR / "f%04d.png"}" '
        f'-vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 23 "{out}"'
    )
    subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    size = out.stat().st_size / 1024 / 1024
    print(f"OK Video: {out} ({size:.1f} MB, ~{frame_idx / FPS:.0f} c)")


if __name__ == "__main__":
    main()
