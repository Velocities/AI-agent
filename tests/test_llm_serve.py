from unittest.mock import MagicMock, patch

from ai_agent.cli.llm_serve import prepare_upstream
from ai_agent.config import Settings
from ai_agent.llm.base import LLMHealthcheck, LLMErrorKind


def test_prepare_upstream_exits_when_healthcheck_fails() -> None:
    settings = Settings()
    console = MagicMock()
    provider = MagicMock()
    provider.healthcheck.return_value = LLMHealthcheck(
        ok=False,
        message="LLM endpoint is unavailable: http://localhost:11434",
        error_kind=LLMErrorKind.UNAVAILABLE,
    )
    session = MagicMock()

    with (
        patch("ai_agent.cli.llm_serve.create_http_session", return_value=session),
        patch("ai_agent.cli.llm_serve.create_llm_provider", return_value=provider),
        patch("ai_agent.cli.llm_serve.warmup_llm") as warmup,
    ):
        assert prepare_upstream(settings, console) is None
        warmup.assert_not_called()
        provider.close.assert_called_once()


def test_prepare_upstream_exits_when_warmup_fails() -> None:
    settings = Settings()
    console = MagicMock()
    console.status.return_value.__enter__.return_value = None
    console.status.return_value.__exit__.return_value = False
    provider = MagicMock()
    provider.healthcheck.return_value = LLMHealthcheck(ok=True, message="ok")
    session = MagicMock()

    with (
        patch("ai_agent.cli.llm_serve.create_http_session", return_value=session),
        patch("ai_agent.cli.llm_serve.create_llm_provider", return_value=provider),
        patch(
            "ai_agent.cli.llm_serve.warmup_llm",
            return_value=(False, "LLM request timed out.", 1.0),
        ),
        patch("ai_agent.cli.llm_serve._system_prompt", return_value="system"),
    ):
        assert prepare_upstream(settings, console) is None
        provider.close.assert_called_once()


def test_prepare_upstream_returns_provider_when_ready() -> None:
    settings = Settings()
    console = MagicMock()
    console.status.return_value.__enter__.return_value = None
    console.status.return_value.__exit__.return_value = False
    provider = MagicMock()
    provider.healthcheck.return_value = LLMHealthcheck(ok=True, message="ok")
    session = MagicMock()

    with (
        patch("ai_agent.cli.llm_serve.create_http_session", return_value=session),
        patch("ai_agent.cli.llm_serve.create_llm_provider", return_value=provider),
        patch(
            "ai_agent.cli.llm_serve.warmup_llm",
            return_value=(True, "ready", 0.4),
        ),
        patch("ai_agent.cli.llm_serve._system_prompt", return_value="system"),
    ):
        assert prepare_upstream(settings, console) == (provider, session)
        provider.close.assert_not_called()
