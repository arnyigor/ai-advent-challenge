"""Plain reporter for compact non-Rich progress output."""

from ui.events import (
    ExperimentFinished,
    ExperimentStarted,
    FallbackTriggered,
    MethodFinished,
    MethodStarted,
    StageFinished,
    StageStarted,
    TaskStarted,
)
from ui.theme import method_label


class PlainReporter:
    def __init__(self, stream=None) -> None:
        self.stream = stream

    def _print(self, text: str) -> None:
        print(text, file=self.stream)

    def emit(self, event: object) -> None:
        if isinstance(event, ExperimentStarted):
            self._print(
                f"DAY 03 · {event.model} · thinking={event.thinking} · "
                f"{event.repeats} repeat(s)"
            )
        elif isinstance(event, TaskStarted):
            self._print(
                f"[repeat {event.repeat + 1}/{event.repeat_total}] "
                f"{event.task_id} · {event.family}"
            )
        elif isinstance(event, MethodStarted):
            self._print(f"  {method_label(event.method)} started")
        elif isinstance(event, StageStarted):
            self._print(f"    {event.stage}...")
        elif isinstance(event, StageFinished):
            s = event.stage
            self._print(
                f"    {s.name}: {s.status} · "
                f"{s.prompt_tokens + s.output_tokens}t · {s.latency_s:.1f}s"
            )
        elif isinstance(event, MethodFinished):
            r = event.result
            mark = "ok" if r.correct else r.status
            self._print(
                f"  {method_label(r.method):<14} {mark:<12} "
                f"answer={r.answer_norm or '-'} calls={r.calls} "
                f"tokens={r.prompt_tokens + r.output_tokens}"
            )
        elif isinstance(event, FallbackTriggered):
            nxt = event.new_model or "none"
            self._print(f"FALLBACK {event.old_model} -> {nxt}: {event.reason}")
        elif isinstance(event, ExperimentFinished):
            self._print(f"COMPLETE · model={event.model} · runs={len(event.results)}")
