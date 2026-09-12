from unittest.mock import MagicMock

from ai_agent.agent.loop import AgentRunResult
from ai_agent.cli.app import present_turn_result, warmup_agent
from ai_agent.cli.errors import (
    is_fatal_startup_kind,
    startup_should_exit,
    turn_should_exit,
)
from ai_agent.llm.base import LLMErrorKind, LLMHealthcheck


def test_startup_exits_when_healthcheck_fails() -> None:
    assert startup_should_exit(healthy=False, warmup_ok=True) is True


def test_startup_exits_when_warmup_fails() -> None:
    assert startup_should_exit(healthy=True, warmup_ok=False) is True


def test_startup_continues_when_healthy() -> None:
    assert startup_should_exit(healthy=True, warmup_ok=True) is False


def test_startup_kinds_are_fatal() -> None:
    for kind in (
        LLMErrorKind.UNAVAILABLE,
        LLMErrorKind.TIMEOUT,
        LLMErrorKind.HTTP,
        LLMErrorKind.PROTOCOL,
        LLMErrorKind.MODEL_NOT_FOUND,
    ):
        assert is_fatal_startup_kind(kind) is True


def test_mid_turn_unavailable_stays_in_repl() -> None:
    assert turn_should_exit(LLMErrorKind.UNAVAILABLE) is False
    assert turn_should_exit(LLMErrorKind.TIMEOUT) is False
    assert turn_should_exit(LLMErrorKind.HTTP) is False
    assert turn_should_exit(LLMErrorKind.PROTOCOL) is False


def test_mid_turn_session_closed_exits() -> None:
    assert turn_should_exit(LLMErrorKind.SESSION_CLOSED) is True


def test_warmup_agent_stops_on_unavailable_endpoint() -> None:
    agent = MagicMock()
    agent.settings.llm_model = "test-model"
    agent.llm.healthcheck.return_value = LLMHealthcheck(
        ok=False,
        message="LLM endpoint is unavailable: http://127.0.0.1:9",
        error_kind=LLMErrorKind.UNAVAILABLE,
    )
    console = MagicMock()

    assert warmup_agent(agent, console) is False
    agent.warmup.assert_not_called()
    console.print.assert_called()
    assert "unavailable" in str(console.print.call_args).lower()


def test_warmup_agent_stops_on_missing_model() -> None:
    agent = MagicMock()
    agent.settings.llm_model = "missing"
    agent.llm.healthcheck.return_value = LLMHealthcheck(
        ok=False,
        message="Model 'missing' not found at http://localhost:11434.",
        error_kind=LLMErrorKind.MODEL_NOT_FOUND,
    )
    console = MagicMock()

    assert warmup_agent(agent, console) is False
    agent.warmup.assert_not_called()


def test_warmup_agent_stops_when_warmup_fails() -> None:
    agent = MagicMock()
    agent.settings.llm_model = "test-model"
    agent.llm.healthcheck.return_value = LLMHealthcheck(ok=True, message="ok")
    agent.warmup.return_value = (False, "LLM request timed out.", 1.2)
    console = MagicMock()
    console.status.return_value.__enter__.return_value = None
    console.status.return_value.__exit__.return_value = False

    assert warmup_agent(agent, console) is False
    agent.warmup.assert_called_once()


def test_warmup_agent_continues_when_ready() -> None:
    agent = MagicMock()
    agent.settings.llm_model = "test-model"
    agent.llm.healthcheck.return_value = LLMHealthcheck(ok=True, message="ok")
    agent.warmup.return_value = (True, "ready", 0.5)
    console = MagicMock()
    console.status.return_value.__enter__.return_value = None
    console.status.return_value.__exit__.return_value = False

    assert warmup_agent(agent, console) is True


def test_present_turn_stays_open_on_unavailable() -> None:
    console = MagicMock()
    result = AgentRunResult(
        final_message="LLM error: LLM endpoint is unavailable.",
        iterations=1,
        error="LLM endpoint is unavailable.",
        error_kind=LLMErrorKind.UNAVAILABLE,
    )
    assert present_turn_result(console, result, streamed=False) is False


def test_present_turn_exits_when_session_closes() -> None:
    console = MagicMock()
    result = AgentRunResult(
        final_message="LLM error: LLM session is gone.",
        iterations=1,
        error="LLM session is gone.",
        error_kind=LLMErrorKind.SESSION_CLOSED,
    )
    assert present_turn_result(console, result, streamed=False) is True
    printed = " ".join(str(call) for call in console.print.call_args_list)
    assert "Exiting" in printed
