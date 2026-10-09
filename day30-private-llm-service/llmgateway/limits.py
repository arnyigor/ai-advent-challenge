"""Rate limiting and the bounded generation queue.

Both structures live in process memory, so the service must run with exactly one
worker (documented in README).
"""
from __future__ import annotations

import asyncio
import time
from collections import deque


class QueueFullError(Exception):
    """All waiting slots are busy; the request must be rejected with 503."""


class QueueTimeoutError(Exception):
    """Waiting for the single generation slot exceeded the wait timeout."""


class SlidingWindowLimiter:
    """Per-key sliding window counter.

    ``check`` both decides and registers: an allowed request consumes a slot, a
    rejected one does not. Rejected requests must therefore not be counted twice.
    """

    def __init__(self, limit, window_sec, clock=time.monotonic):
        self.limit = limit
        self.window_sec = float(window_sec)
        self._clock = clock
        self._hits = {}

    def check(self, key):
        """Register a request for ``key``. Returns (allowed, retry_after_sec)."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window_sec:
            hits.popleft()
        if len(hits) >= self.limit:
            return False, max(self.window_sec - (now - hits[0]), 0.0)
        hits.append(now)
        return True, 0.0

    def reset(self, key=None):
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


class GenerationQueue:
    """One active generation, at most ``max_waiting`` requests waiting behind it.

    ``release`` is intentionally synchronous: it must stay safe when the HTTP
    handler is cancelled (client disconnect), where awaiting inside a
    ``finally`` block is not reliable.
    Fairness is not guaranteed - a newly arriving request may take the slot
    before a request that has been waiting.
    """

    def __init__(self, max_waiting, wait_timeout_sec):
        self.max_waiting = int(max_waiting)
        self.wait_timeout_sec = float(wait_timeout_sec)
        self.active = False
        self.waiting = 0
        self._lock = asyncio.Lock()
        self._free = asyncio.Event()

    def stats(self):
        return {"active": self.active, "waiting": self.waiting, "max_waiting": self.max_waiting}

    async def acquire(self):
        """Take the generation slot. Returns seconds spent waiting.

        Raises QueueFullError when the waiting room is full, QueueTimeoutError
        when the wait exceeded the timeout.
        """
        loop = asyncio.get_running_loop()
        start = loop.time()
        async with self._lock:
            if not self.active:
                self.active = True
                return 0.0
            if self.waiting >= self.max_waiting:
                raise QueueFullError(
                    f"queue is full: {self.waiting} waiting, {self.max_waiting} allowed"
                )
            self.waiting += 1
        try:
            while True:
                async with self._lock:
                    self._free.clear()
                    if not self.active:
                        self.active = True
                        return loop.time() - start
                remaining = self.wait_timeout_sec - (loop.time() - start)
                if remaining <= 0:
                    raise QueueTimeoutError(
                        f"waited more than {self.wait_timeout_sec:.0f}s for the generation slot"
                    )
                try:
                    await asyncio.wait_for(self._free.wait(), remaining)
                except (asyncio.TimeoutError, TimeoutError):
                    raise QueueTimeoutError(
                        f"waited more than {self.wait_timeout_sec:.0f}s for the generation slot"
                    ) from None
        finally:
            async with self._lock:
                self.waiting -= 1

    def release(self):
        self.active = False
        self._free.set()
