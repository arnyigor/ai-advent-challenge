BOX_WIDTH = 64

CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"


def truncate(text, max_len=90):
    text = text.strip()
    return text if len(text) <= max_len else text[:max_len].rstrip() + "..."


def pass_fail(ok):
    label = "PASS" if ok else "FAIL"
    color = GREEN if ok else RED
    return f"{color}[{label}]{RESET}"


def print_box(lines, width=BOX_WIDTH):
    """Рисует рамку в Unicode-стиле (╔═╗) шириной `width` символов внутри.

    ВАЖНО: в lines нельзя передавать ANSI-escape (цвета). ljust считает длину
    строки в символах, а не в видимой ширине — escape-последовательности
    разъедут рамку. Цветные значения нужно собирать ДО строк рамки или вне её.
    """
    top = "╔" + "═" * width + "╗"
    bottom = "╚" + "═" * width + "╝"
    print(top)
    for line in lines:
        print("║ " + line.ljust(width - 1) + "║")
    print(bottom)


def wait_for_enter(prompt="Press Enter to run..."):
    try:
        input(f"\n{prompt}")
    except (EOFError, KeyboardInterrupt):
        print()
