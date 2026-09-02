"""Rich live dashboard for Day 3."""

from __future__ import annotations

import time

from scoring import accuracy, cost_per_correct, self_consistency
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
from ui.final_report import format_pareto_summary
from ui.theme import METHOD_COLORS, STATUS_COLORS, method_label


class DashboardReporter:
    def __init__(self, methods, tasks, video_mode=False, width=None) -> None:
        from rich.console import Console
        from rich.live import Live

        self.methods = methods
        self.tasks = tasks
        self.video_mode = video_mode
        self.console = Console(width=width or (140 if video_mode else None))
        self._Live = Live
        self.live = None
        self.started_at = time.monotonic()
        self.model = "-"
        self.thinking = "-"
        self.repeats = 0
        self.total_calls_estimate = 0
        self.current_task = None
        self.current_repeat = 0
        self.current_task_index = 0
        self.method_states = {
            m: {
                "status": "waiting",
                "answer": "-",
                "correct": None,
                "calls": 0,
                "tokens": 0,
                "latency": 0.0,
                "stages": [],
            }
            for m in methods
        }
        self.results = []
        self.failures = {
            "wrong": 0,
            "unparseable": 0,
            "truncated": 0,
            "blocked": 0,
            "contaminated": 0,
            "error": 0,
        }
        self.fallback = None
        self.complete = False

    def __enter__(self):
        self.live = self._Live(
            self.render(),
            console=self.console,
            refresh_per_second=8 if self.video_mode else 4,
            transient=False,
        )
        self.live.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.live:
            self.live.update(self.render())
            self.live.__exit__(exc_type, exc, tb)
        return False

    def emit(self, event: object) -> None:
        if isinstance(event, ExperimentStarted):
            self.model = event.model
            self.thinking = event.thinking
            self.repeats = event.repeats
            self.total_calls_estimate = event.total_calls_estimate
            self.complete = False
        elif isinstance(event, TaskStarted):
            self.current_task = event
            self.current_repeat = event.repeat
            self.current_task_index = event.task_index
            for state in self.method_states.values():
                state.update(
                    {
                        "status": "waiting",
                        "answer": "-",
                        "correct": None,
                        "calls": 0,
                        "tokens": 0,
                        "latency": 0.0,
                        "stages": [],
                    }
                )
        elif isinstance(event, MethodStarted):
            self.method_states[event.method]["status"] = "running"
        elif isinstance(event, StageStarted):
            state = self.method_states[event.method]
            state["status"] = "running"
            state["stages"].append(
                {"name": event.stage, "status": "running", "tokens": 0, "latency": 0.0}
            )
        elif isinstance(event, StageFinished):
            state = self.method_states[event.method]
            stage = event.stage
            for item in reversed(state["stages"]):
                if item["name"] == stage.name and item["status"] == "running":
                    item.update(
                        {
                            "status": stage.status,
                            "tokens": stage.prompt_tokens + stage.output_tokens,
                            "latency": stage.latency_s,
                        }
                    )
                    break
        elif isinstance(event, MethodFinished):
            r = event.result
            state = self.method_states[r.method]
            state.update(
                {
                    "status": "correct" if r.correct else r.status,
                    "answer": r.answer_norm or "-",
                    "correct": r.correct,
                    "calls": r.calls,
                    "tokens": r.prompt_tokens + r.output_tokens,
                    "latency": r.latency_s,
                    "stages": [
                        {
                            "name": s.name,
                            "status": s.status,
                            "tokens": s.prompt_tokens + s.output_tokens,
                            "latency": s.latency_s,
                        }
                        for s in r.stages
                    ],
                }
            )
            self.results.append(r)
            if r.status == "ok" and not r.correct:
                self.failures["wrong"] += 1
            elif r.status != "ok":
                self.failures[r.status if r.status in self.failures else "error"] += 1
        elif isinstance(event, FallbackTriggered):
            self.fallback = event
            self.results.clear()
        elif isinstance(event, ExperimentFinished):
            self.results = event.results
            self.complete = True

        if self.live:
            self.live.update(self.render())

    def render(self):
        from rich.align import Align
        from rich.columns import Columns
        from rich.console import Group
        from rich.panel import Panel
        from rich.progress import BarColumn, Progress, TextColumn
        from rich.table import Table
        from rich.text import Text

        elapsed = int(time.monotonic() - self.started_at)
        calls_done = sum(r.calls for r in self.results)
        status = "COMPLETE" if self.complete else "LIVE"
        header = Table.grid(expand=True)
        header.add_column(justify="left")
        header.add_column(justify="right")
        header.add_row(
            "[bold]AI ADVENT CHALLENGE · DAY 03[/bold]  REASONING LAB",
            f"[bold]{status}[/bold]",
        )
        header.add_row(
            f"{self.model}   thinking={self.thinking}   "
            f"repeat {self.current_repeat + 1}/{self.repeats or '-'}   "
            f"task {self.current_task_index}/{len(self.tasks)}",
            f"elapsed {elapsed // 60:02}:{elapsed % 60:02}   "
            f"API {calls_done}/~{self.total_calls_estimate or 0}",
        )
        if self.fallback:
            header.add_row(
                f"[yellow]fallback {self.fallback.old_model} -> "
                f"{self.fallback.new_model or 'none'}[/yellow]",
                "",
            )

        task_panel = self._task_panel()
        cards = [self._method_card(m) for m in self.methods]
        width = self.console.size.width
        if width >= 130:
            method_block = Columns(cards, equal=True, expand=True)
        elif width >= 90:
            method_block = Group(
                Columns(cards[:2], equal=True, expand=True),
                Columns(cards[2:], equal=True, expand=True),
            )
        else:
            method_block = Group(*cards)

        progress = Progress(
            TextColumn("Experiment"),
            BarColumn(bar_width=None),
            TextColumn(f"{len(self.results)}/{max(1, len(self.methods) * len(self.tasks) * max(self.repeats, 1))} runs"),
            expand=True,
        )
        total_runs = max(1, len(self.methods) * len(self.tasks) * max(self.repeats, 1))
        task_id = progress.add_task("run", total=total_runs, completed=len(self.results))

        footer = Table.grid(expand=True)
        footer.add_row(progress)
        footer.add_row(self._failure_line())

        body = [Panel(header, border_style="cyan"), task_panel, method_block, self._scoreboard(), Panel(footer)]
        if self.complete:
            body.append(Panel(format_pareto_summary(self.results, self.methods), title="FINAL"))
        return Group(*body)

    def _task_panel(self):
        from rich.panel import Panel

        if not self.current_task:
            return Panel("waiting for first task", title="CURRENT TASK")
        baseline = f"~{self.current_task.baseline:.0%}" if self.current_task.baseline else "~0%"
        text = (
            f"[bold]{self.current_task.task_id}[/bold] · {self.current_task.family.upper()}\n"
            f"{self.current_task.prompt}\n\n"
            f"Repeat {self.current_task.repeat + 1}/{self.current_task.repeat_total}   "
            f"Baseline {baseline}   Gold HIDDEN"
        )
        return Panel(text, title="CURRENT TASK", border_style="blue")

    def _method_card(self, method):
        from rich.panel import Panel
        from rich.table import Table

        state = self.method_states[method]
        color = METHOD_COLORS.get(method, "white")
        status = state["status"]
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(justify="right")
        table.add_row("Status", self._status_text(status))
        table.add_row("Calls", str(state["calls"]))
        table.add_row("Tokens", str(state["tokens"] or "-"))
        table.add_row("Latency", f"{state['latency']:.1f}s" if state["latency"] else "-")
        for stage in state["stages"][:5]:
            table.add_row(stage["name"], self._status_text(stage["status"]))
        table.add_row("Answer", str(state["answer"])[:36])
        return Panel(table, title=method_label(method), border_style=color)

    def _scoreboard(self):
        from rich.panel import Panel
        from rich.table import Table

        table = Table(expand=True)
        table.add_column("Method")
        table.add_column("Accuracy", justify="right")
        table.add_column("Valid", justify="right")
        table.add_column("Consistency", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Cost/correct", justify="right")
        for method in self.methods:
            rows = [r for r in self.results if r.method == method]
            correct, total = accuracy(rows)
            valid = sum(1 for r in rows if r.status != "contaminated")
            tokens = sum((r.prompt_tokens or 0) + (r.output_tokens or 0) for r in rows)
            consistency = self_consistency(rows)
            cpc = cost_per_correct(rows)
            table.add_row(
                method_label(method),
                f"{correct}/{total}",
                f"{valid}/{len(rows)}",
                "-" if consistency is None else f"{consistency:.2f}",
                _compact_number(tokens),
                "-" if cpc is None else str(int(cpc)),
            )
        return Panel(table, title="LIVE SCORE", border_style="white")

    def _failure_line(self) -> str:
        parts = []
        for key, value in self.failures.items():
            label = key.upper()
            parts.append(f"[red]{label} {value}[/red]" if value else f"[dim]{label} 0[/dim]")
        return "   ".join(parts)

    def _status_text(self, status):
        color = STATUS_COLORS.get(status, "white")
        return f"[{color}]{status.upper()}[/{color}]"


def _compact_number(value):
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)
