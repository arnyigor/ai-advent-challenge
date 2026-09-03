import time


class Pacer:
    """Минимальный пейсер: gap между вызовами по rpm, с кооперативной отменой."""

    def __init__(self, rpm, cancel_event=None, cancelled_exc=None):
        self.gap = 60.0 / rpm if rpm and rpm > 0 else 0.0
        self._last = None
        self.cancel_event = cancel_event
        self.cancelled_exc = cancelled_exc or RuntimeError

    def wait(self):
        now = time.monotonic()
        if self._last is not None and self.gap:
            d = self.gap - (now - self._last)
            if d > 0:
                if self.cancel_event is not None:
                    if self.cancel_event.wait(d):
                        raise self.cancelled_exc()
                else:
                    time.sleep(d)
        self._last = time.monotonic()
