"""Провайдеро-независимый клиент вызова LLM: пейсер + ретраи + опциональный
стриминг поверх реестра tools/llm/registry.py.

Не знает ничего про UI/репортеры конкретного дня — если дню нужны свои
события (как ui.events в Day 3), он оборачивает call_stream() в подклассе,
а не переопределяет диспетчеризацию по провайдеру заново (см.
day03-reasoning-modes/day3_reasoning_modes.py:Client)."""

from tools.llm._transport import LLMCancelledError
from tools.llm.registry import model_label, resolve_provider, split_model_spec


class Client:
    def __init__(
        self,
        model,
        pacer=None,
        quiet=False,
        cancel_event=None,
        stream=False,
        retry_logger=None,
        cancelled_exc=None,
    ):
        self.provider_name, parsed_model = split_model_spec(model)
        self.provider = resolve_provider(self.provider_name)
        self.model = parsed_model or self.provider.default_model
        self.model_spec = model_label(f"{self.provider_name}:{self.model}")
        self.pacer = pacer
        self.quiet = quiet
        self.cancel_event = cancel_event
        self.stream = stream
        self.retry_logger = retry_logger
        self.cancelled_exc = cancelled_exc or LLMCancelledError

    def _raise_cancelled(self):
        raise self.cancelled_exc()

    def call(self, prompt, gcfg=None, system_instruction=None):
        if self.cancel_event is not None and self.cancel_event.is_set():
            self._raise_cancelled()
        if self.pacer:
            self.pacer.wait()
        try:
            return self.provider.call_with_retries(
                self.model,
                prompt,
                gcfg,
                system_instruction=system_instruction,
                quiet=self.quiet,
                retry_logger=None if self.quiet else self.retry_logger,
                cancel_event=self.cancel_event,
            )
        except LLMCancelledError:
            self._raise_cancelled()

    def call_stream(
        self,
        prompt,
        gcfg=None,
        system_instruction=None,
        on_text=None,
        on_state=None,
        on_retry=None,
    ):
        if not self.stream:
            return self.call(prompt, gcfg, system_instruction=system_instruction)
        if self.cancel_event is not None and self.cancel_event.is_set():
            self._raise_cancelled()
        if self.pacer:
            self.pacer.wait()
        try:
            return self.provider.call_stream_with_retries(
                self.model,
                prompt,
                gcfg,
                system_instruction=system_instruction,
                quiet=self.quiet,
                retry_logger=None if self.quiet else self.retry_logger,
                cancel_event=self.cancel_event,
                on_text=on_text,
                on_state=on_state,
                on_retry=on_retry,
            )
        except LLMCancelledError:
            self._raise_cancelled()
