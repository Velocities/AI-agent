from unittest.mock import MagicMock, patch

from ai_agent.cli.llm_serve import prepare_upstream
from ai_agent.config import Settings
from ai_agent.llm.server.engine.base import EngineHealth


def test_prepare_upstream_exits_when_healthcheck_fails() -> None:
    settings = Settings()
    console = MagicMock()
    engine = MagicMock()
    engine.healthcheck.return_value = EngineHealth(
        ok=False,
        message="LLM endpoint is unavailable: http://localhost:11434",
    )

    with (
        patch("ai_agent.cli.llm_serve.create_engine", return_value=engine),
        patch("ai_agent.cli.llm_serve.warmup_engine") as warmup,
    ):
        assert prepare_upstream(settings, console) is None
        warmup.assert_not_called()
        engine.close.assert_called_once()


def test_prepare_upstream_exits_when_warmup_fails() -> None:
    settings = Settings()
    console = MagicMock()
    console.status.return_value.__enter__.return_value = None
    console.status.return_value.__exit__.return_value = False
    engine = MagicMock()
    engine.engine_name = "Ollama"
    engine.model = "test-model"
    engine.healthcheck.return_value = EngineHealth(ok=True, message="ok")

    with (
        patch("ai_agent.cli.llm_serve.create_engine", return_value=engine),
        patch(
            "ai_agent.cli.llm_serve.warmup_engine",
            return_value=(False, "LLM request timed out.", 1.0),
        ),
        patch("ai_agent.cli.llm_serve._system_prompt", return_value="system"),
    ):
        assert prepare_upstream(settings, console) is None
        engine.close.assert_called_once()


def test_prepare_upstream_returns_engine_when_ready() -> None:
    settings = Settings()
    console = MagicMock()
    console.status.return_value.__enter__.return_value = None
    console.status.return_value.__exit__.return_value = False
    engine = MagicMock()
    engine.engine_name = "Ollama"
    engine.model = "test-model"
    engine.healthcheck.return_value = EngineHealth(ok=True, message="ok")

    with (
        patch("ai_agent.cli.llm_serve.create_engine", return_value=engine),
        patch(
            "ai_agent.cli.llm_serve.warmup_engine",
            return_value=(True, "ready", 0.4),
        ),
        patch("ai_agent.cli.llm_serve._system_prompt", return_value="system"),
    ):
        assert prepare_upstream(settings, console) is engine
        engine.close.assert_not_called()
