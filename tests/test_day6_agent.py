import json
import sys
import threading
from pathlib import Path

import pytest


DAY06_DIR = Path(__file__).resolve().parents[1] / "day06-first-agent"
if str(DAY06_DIR) not in sys.path:
    sys.path.insert(0, str(DAY06_DIR))

from agent import (
    AgentConfig,
    AgentCancelledError,
    AgentStore,
    AgentUnavailableError,
    ChatAgent,
    JudgeResult,
    Message,
    OutputPolicyError,
    ProviderError,
    ProviderCancelledError,
    ProviderReply,
    TokenUsage,
)


class FakeProvider:
    def __init__(self, provider_id="fake", outcomes=None, available=True):
        self.id = provider_id
        self.label = provider_id.title()
        self.default_model = f"{provider_id}-model"
        self._available = available
        self._outcomes = list(outcomes or ["Ответ агента"])
        self.calls = []
        self.cancel_events = []

    def available(self):
        return self._available

    def generate(self, messages, config, cancel_event):
        self.calls.append((tuple(messages), config))
        self.cancel_events.append(cancel_event)
        index = min(len(self.calls) - 1, len(self._outcomes) - 1)
        outcome = self._outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, ProviderReply):
            return outcome
        return ProviderReply(
            text=outcome,
            provider=self.id,
            model=self.default_model,
        )


def provider_reply(provider_id, text, usage=None):
    return ProviderReply(
        text=text,
        provider=provider_id,
        model=f"{provider_id}-model",
        usage=usage or TokenUsage(),
    )


def test_basic_call_normalizes_input_and_passes_config_to_provider():
    config = AgentConfig(
        system_prompt="Тестовый агент",
        temperature=0.25,
        max_output_tokens=77,
    )
    provider = FakeProvider()

    reply = ChatAgent([provider], config=config).ask("  Привет  ")

    assert provider.calls == [((Message("user", "Привет"),), config)]
    assert reply.text == "Ответ агента"
    assert reply.provider == "fake"
    assert reply.model == "fake-model"
    assert reply.attempts == ({"provider": "fake", "status": "ok"},)


def test_agent_keeps_history_between_requests():
    provider = FakeProvider(outcomes=["Первый ответ", "Второй ответ"])
    agent = ChatAgent([provider])

    agent.ask("Первый вопрос")
    agent.ask("Второй вопрос")

    assert provider.calls[1][0] == (
        Message("user", "Первый вопрос"),
        Message("assistant", "Первый ответ"),
        Message("user", "Второй вопрос"),
    )
    assert agent.history == (
        Message("user", "Первый вопрос"),
        Message("assistant", "Первый ответ"),
        Message("user", "Второй вопрос"),
        Message("assistant", "Второй ответ"),
    )


def test_agent_falls_back_in_configured_order():
    first = FakeProvider("gemini", [ProviderError("temporary failure")])
    second = FakeProvider("routerai", ["Резервный ответ"])

    reply = ChatAgent([first, second]).ask("Вопрос")

    assert len(first.calls) == 1
    assert len(second.calls) == 1
    assert reply.provider == "routerai"
    assert reply.attempts == (
        {"provider": "gemini", "status": "failed", "error": "ProviderError"},
        {"provider": "routerai", "status": "ok"},
    )


def test_unavailable_provider_is_skipped_without_generate_call():
    unavailable = FakeProvider("gemini", available=False)
    fallback = FakeProvider("routerai", ["Готово"])

    reply = ChatAgent([unavailable, fallback]).ask("Вопрос")

    assert unavailable.calls == []
    assert reply.provider == "routerai"
    assert reply.attempts[0] == {"provider": "gemini", "status": "skipped"}


def test_all_provider_failures_raise_safe_error_and_preserve_state():
    first = FakeProvider("one", [ProviderError("secret provider detail")])
    second = FakeProvider("two", [ProviderError("another private detail")])
    agent = ChatAgent([first, second])

    with pytest.raises(AgentUnavailableError) as caught:
        agent.ask("Вопрос")

    assert str(caught.value) == "Ни один LLM-провайдер сейчас не смог ответить"
    assert "secret" not in str(caught.value)
    assert caught.value.attempts == (
        {"provider": "one", "status": "failed", "error": "ProviderError"},
        {"provider": "two", "status": "failed", "error": "ProviderError"},
    )
    assert agent.history == ()
    assert agent.session_usage == TokenUsage()


@pytest.mark.parametrize(
    ("invalid_input", "error_type"),
    [
        ("   ", ValueError),
        (None, ValueError),
        (123, TypeError),
        ("слишком", ValueError),
    ],
)
def test_invalid_input_is_rejected_before_provider_and_state_is_unchanged(
    invalid_input, error_type
):
    provider = FakeProvider(
        outcomes=[
            provider_reply("fake", "Есть ответ", TokenUsage(2, 3, 5, True)),
            "Не должен вызываться",
        ]
    )
    agent = ChatAgent([provider], config=AgentConfig(max_input_chars=6))
    agent.ask("ok")
    history_before = agent.history
    usage_before = agent.session_usage
    calls_before = len(provider.calls)

    with pytest.raises(error_type):
        agent.ask(invalid_input)

    assert len(provider.calls) == calls_before
    assert agent.history == history_before
    assert agent.session_usage == usage_before


@pytest.mark.parametrize("invalid_output", ["   ", "12345"])
def test_invalid_output_causes_controlled_fallback(invalid_output):
    first = FakeProvider("one", [invalid_output])
    second = FakeProvider("two", ["ok"])
    config = AgentConfig(max_output_chars=4)

    reply = ChatAgent([first, second], config=config).ask("ok")

    assert reply.text == "ok"
    assert reply.attempts == (
        {
            "provider": "one",
            "status": "failed",
            "error": "OutputPolicyError",
        },
        {"provider": "two", "status": "ok"},
    )


def test_all_invalid_outputs_raise_unavailable_and_leave_existing_state_unchanged():
    accepted_usage = TokenUsage(1, 2, 3, True)
    first = FakeProvider(
        "one",
        [provider_reply("one", "ok", accepted_usage), provider_reply("one", "", TokenUsage(9, 9, 18, True))],
    )
    second = FakeProvider("two", ["12345"])
    agent = ChatAgent([first, second], config=AgentConfig(max_output_chars=4))
    agent.ask("seed")
    history_before = agent.history
    usage_before = agent.session_usage

    with pytest.raises(AgentUnavailableError) as caught:
        agent.ask("next")

    assert [attempt["error"] for attempt in caught.value.attempts] == [
        "OutputPolicyError",
        "OutputPolicyError",
    ]
    assert agent.history == history_before
    assert agent.session_usage == usage_before


def test_default_output_policy_rejects_non_string_output():
    provider = FakeProvider("bad", [provider_reply("bad", None)])

    with pytest.raises(AgentUnavailableError) as caught:
        ChatAgent([provider]).ask("Вопрос")

    assert caught.value.attempts[0]["error"] == OutputPolicyError.__name__


def test_token_usage_addition_combines_counts_and_reported_flag():
    unreported = TokenUsage()
    reported = TokenUsage(3, 5, 8, True, 2)

    assert unreported + reported == TokenUsage(3, 5, 8, True, 2)
    assert reported + TokenUsage(2, 1, 3, True, 4) == TokenUsage(
        5, 6, 11, True, 6
    )
    assert reported.__add__(object()) is NotImplemented


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        ({"input_tokens": -1}, ValueError),
        ({"output_tokens": -1}, ValueError),
        ({"total_tokens": -1}, ValueError),
        ({"reasoning_tokens": -1}, ValueError),
        ({"input_tokens": 1.5}, TypeError),
        ({"input_tokens": True}, TypeError),
        ({"reported": 1}, TypeError),
        ({"reasoning_tokens": True}, TypeError),
    ],
)
def test_token_usage_validation(kwargs, error_type):
    with pytest.raises(error_type):
        TokenUsage(**kwargs)


def test_reply_usage_is_current_and_session_usage_accumulates_across_calls():
    first_usage = TokenUsage(2, 3, 5, True)
    second_usage = TokenUsage(7, 11, 18, True)
    provider = FakeProvider(
        outcomes=[
            provider_reply("fake", "Один", first_usage),
            provider_reply("fake", "Два", second_usage),
        ]
    )
    agent = ChatAgent([provider])

    first = agent.ask("one")
    second = agent.ask("two")

    assert first.usage == first_usage
    assert first.session_usage == first_usage
    assert second.usage == second_usage
    assert second.session_usage == TokenUsage(9, 14, 23, True)
    assert agent.session_usage == second.session_usage


def test_reset_clears_history_and_session_usage():
    provider = FakeProvider(
        outcomes=[provider_reply("fake", "Ответ", TokenUsage(4, 6, 10, True))]
    )
    agent = ChatAgent([provider])
    agent.ask("Вопрос")

    agent.reset()

    assert agent.history == ()
    assert agent.session_usage == TokenUsage()


def test_usage_from_failed_output_attempt_is_not_counted():
    rejected_usage = TokenUsage(100, 100, 200, True)
    accepted_usage = TokenUsage(2, 3, 5, True)
    rejected = FakeProvider(
        "rejected", [provider_reply("rejected", "", rejected_usage)]
    )
    accepted = FakeProvider(
        "accepted", [provider_reply("accepted", "Готово", accepted_usage)]
    )

    reply = ChatAgent([rejected, accepted]).ask("Вопрос")

    assert reply.usage == accepted_usage
    assert reply.session_usage == accepted_usage


def test_judge_is_disabled_by_default_and_does_not_add_provider_calls():
    provider = FakeProvider()

    reply = ChatAgent([provider]).ask("Вопрос")

    assert len(provider.calls) == 1
    assert reply.judgement is None


def test_explicit_judge_returns_judge_result():
    class FakeJudge:
        def __init__(self):
            self.calls = []

        def evaluate(self, messages, reply, config):
            self.calls.append((tuple(messages), reply, config))
            return JudgeResult(True, "Ответ соответствует запросу")

    provider = FakeProvider()
    judge = FakeJudge()
    config = AgentConfig(temperature=0.1)

    reply = ChatAgent([provider], config=config, judge=judge).ask("Вопрос")

    assert reply.judgement == JudgeResult(True, "Ответ соответствует запросу")
    assert len(judge.calls) == 1
    assert judge.calls[0][0] == (Message("user", "Вопрос"),)
    assert judge.calls[0][1].text == "Ответ агента"
    assert judge.calls[0][2] is config


def test_invalid_judge_result_leaves_history_and_usage_unchanged():
    class InvalidJudge:
        def evaluate(self, messages, reply, config):
            return {"passed": True}

    usage = TokenUsage(3, 4, 7, True)
    provider = FakeProvider(outcomes=[provider_reply("fake", "Ответ", usage)])
    agent = ChatAgent([provider], judge=InvalidJudge())

    with pytest.raises(TypeError, match="Judge"):
        agent.ask("Вопрос")

    assert agent.history == ()
    assert agent.session_usage == TokenUsage()


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        ({"system_prompt": None}, TypeError),
        ({"temperature": True}, TypeError),
        ({"temperature": float("nan")}, ValueError),
        ({"temperature": -0.01}, ValueError),
        ({"temperature": 2.01}, ValueError),
        ({"max_output_tokens": 0}, ValueError),
        ({"max_output_tokens": 1.5}, TypeError),
        ({"max_history_messages": 1}, ValueError),
        ({"max_input_chars": 0}, ValueError),
        ({"max_output_chars": 0}, ValueError),
        ({"thinking_level": None}, TypeError),
        ({"thinking_level": "medium"}, ValueError),
    ],
)
def test_agent_config_rejects_invalid_bounds_and_types(kwargs, error_type):
    with pytest.raises(error_type):
        AgentConfig(**kwargs)


def test_agent_config_accepts_documented_boundary_values():
    config = AgentConfig(
        temperature=0,
        max_output_tokens=1,
        max_history_messages=2,
        max_input_chars=1,
        max_output_chars=1,
        thinking_level="high",
    )

    assert config.temperature == 0
    assert config.max_output_tokens == 1
    assert config.thinking_level == "high"


def test_to_dict_serializes_nested_usage_and_judgement_as_json_safe_data():
    usage = TokenUsage(5, 8, 13, True, 3)

    class PassingJudge:
        def evaluate(self, messages, reply, config):
            return JudgeResult(True, "ok")

    reply = ChatAgent(
        [FakeProvider(outcomes=[provider_reply("fake", "Готово", usage)])],
        judge=PassingJudge(),
    ).ask("Вопрос")

    payload = reply.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["usage"] == {
        "input_tokens": 5,
        "output_tokens": 8,
        "total_tokens": 13,
        "reported": True,
        "reasoning_tokens": 3,
    }
    assert payload["session_usage"] == payload["usage"]
    assert payload["judgement"] == {"passed": True, "reason": "ok"}
    assert payload["attempts"] == [{"provider": "fake", "status": "ok"}]
    assert json.loads(encoded) == payload


def test_history_trimming_uses_configured_message_limit():
    provider = FakeProvider(outcomes=["A1", "A2", "A3", "A4"])
    agent = ChatAgent([provider], config=AgentConfig(max_history_messages=2))

    agent.ask("Q1")
    agent.ask("Q2")
    agent.ask("Q3")

    assert agent.history == (Message("user", "Q3"), Message("assistant", "A3"))

    agent.ask("Q4")

    assert provider.calls[3][0] == (
        Message("user", "Q3"),
        Message("assistant", "A3"),
        Message("user", "Q4"),
    )


def test_cancel_before_provider_generate_stops_without_fallback_or_state_change():
    available_started = threading.Event()
    release_available = threading.Event()

    class SlowAvailabilityProvider(FakeProvider):
        def available(self):
            available_started.set()
            assert release_available.wait(1)
            return True

    first = SlowAvailabilityProvider(
        "first", [provider_reply("first", "не должен вернуться", TokenUsage(9, 9, 18, True))]
    )
    fallback = FakeProvider("fallback")
    agent = ChatAgent([first, fallback])
    caught = []

    worker = threading.Thread(target=lambda: _capture_ask_error(agent, caught))
    worker.start()
    assert available_started.wait(1)
    assert agent.cancel() is True
    release_available.set()
    worker.join(1)

    assert not worker.is_alive()
    assert len(caught) == 1 and isinstance(caught[0], AgentCancelledError)
    assert first.calls == []
    assert fallback.calls == []
    assert agent.history == ()
    assert agent.session_usage == TokenUsage()
    assert agent.cancel() is False


def test_cancel_during_provider_call_never_falls_back_or_commits_reply():
    call_started = threading.Event()

    class CooperativeProvider(FakeProvider):
        def generate(self, messages, config, cancel_event):
            self.calls.append((tuple(messages), config))
            self.cancel_events.append(cancel_event)
            call_started.set()
            assert cancel_event.wait(1)
            raise ProviderCancelledError("cancelled")

    first = CooperativeProvider("first")
    fallback = FakeProvider("fallback")
    agent = ChatAgent([first, fallback])
    caught = []

    worker = threading.Thread(target=lambda: _capture_ask_error(agent, caught))
    worker.start()
    assert call_started.wait(1)
    assert agent.cancel() is True
    worker.join(1)

    assert not worker.is_alive()
    assert len(caught) == 1 and isinstance(caught[0], AgentCancelledError)
    assert fallback.calls == []
    assert agent.history == ()
    assert agent.session_usage == TokenUsage()


def test_ask_with_provider_id_skips_other_providers():
    first = FakeProvider("one", ["не должен вернуться"])
    second = FakeProvider("two", ["Ответ two"])
    agent = ChatAgent([first, second])

    reply = agent.ask("Вопрос", provider_id="two")

    assert first.calls == []
    assert reply.provider == "two"
    assert reply.attempts == ({"provider": "two", "status": "ok"},)


def test_ask_with_unknown_provider_id_raises_without_calling_any_provider():
    provider = FakeProvider("one")
    agent = ChatAgent([provider])

    with pytest.raises(ValueError, match="one-bad"):
        agent.ask("Вопрос", provider_id="one-bad")

    assert provider.calls == []


def test_ask_with_thinking_level_override_reaches_provider_without_changing_default():
    provider = FakeProvider()
    agent = ChatAgent([provider], config=AgentConfig(thinking_level="minimal"))

    agent.ask("Вопрос", thinking_level="high")

    assert provider.calls[0][1].thinking_level == "high"
    assert agent.config.thinking_level == "minimal"


def test_ask_with_invalid_thinking_level_override_raises_and_changes_nothing():
    provider = FakeProvider()
    agent = ChatAgent([provider])

    with pytest.raises(ValueError):
        agent.ask("Вопрос", thinking_level="medium")

    assert provider.calls == []
    assert agent.history == ()


def test_agent_store_cancel_does_not_create_unknown_session():
    store = AgentStore(lambda: ChatAgent([FakeProvider()]))

    assert store.cancel("missing") is False
    assert store._agents == {}


def _capture_ask_error(agent, caught):
    try:
        agent.ask("вопрос")
    except Exception as exc:  # exception is asserted by the calling test
        caught.append(exc)
