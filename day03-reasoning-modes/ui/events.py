"""Structured events emitted by the Day 3 experiment runner."""

from dataclasses import dataclass
from typing import Protocol

from methods import MethodResult, StageResult


class Reporter(Protocol):
    def emit(self, event: object) -> None:
        ...


class NullReporter:
    def emit(self, event: object) -> None:
        return None


class RecordingReporter:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


@dataclass(frozen=True)
class ExperimentStarted:
    model: str
    thinking: str
    repeats: int
    tasks_total: int
    methods: list[str]
    total_calls_estimate: int


@dataclass(frozen=True)
class TaskStarted:
    task_id: str
    family: str
    prompt: str
    repeat: int
    repeat_total: int
    task_index: int
    task_total: int
    baseline: float


@dataclass(frozen=True)
class MethodStarted:
    method: str


@dataclass(frozen=True)
class StageStarted:
    method: str
    stage: str
    prompt: str = ""


@dataclass(frozen=True)
class RequestStateChanged:
    method: str
    stage: str
    state: str


@dataclass(frozen=True)
class RequestRetrying:
    method: str
    stage: str
    attempt: int
    wait_s: float
    reason: str


@dataclass(frozen=True)
class StageOutputDelta:
    method: str
    stage: str
    text: str


@dataclass(frozen=True)
class StageFinished:
    method: str
    stage: StageResult


@dataclass(frozen=True)
class MethodFinished:
    result: MethodResult


@dataclass(frozen=True)
class FallbackTriggered:
    old_model: str
    new_model: str | None
    reason: str


@dataclass(frozen=True)
class ExperimentFinished:
    results: list[MethodResult]
    model: str


@dataclass(frozen=True)
class ExperimentCancelled:
    completed_methods: int
