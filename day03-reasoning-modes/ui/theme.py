"""Shared labels and colors for Day 3 renderers."""

METHOD_LABELS = {
    "direct": "DIRECT",
    "cot": "STEP-BY-STEP",
    "self_prompt": "SELF-PROMPT",
    "panel": "EXPERT PANEL",
}

METHOD_COLORS = {
    "direct": "cyan",
    "cot": "yellow",
    "self_prompt": "magenta",
    "panel": "green",
}

STATUS_COLORS = {
    "ok": "green",
    "running": "yellow",
    "waiting": "dim",
    "skipped": "dim",
    "truncated": "red",
    "blocked": "red",
    "contaminated": "red",
    "unparseable": "red",
    "error": "red",
}


def method_label(method: str) -> str:
    return METHOD_LABELS.get(method, method.upper())
