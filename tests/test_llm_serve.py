from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from ai_agent.cli.llm_serve import main, prepare_upstream
from ai_agent.config import Settings
from ai_agent.llm.server.engine.base import EngineHealth


@contextmanager
def _noop_managed_process(*_args, **_kwargs):
    process = MagicMock()
    process.upstream_url = "http://localhost:11434"
    process.started_by_us = False
    yield process


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


def test_main_wraps_serving_in_managed_engine_process() -> None:
    settings = Settings()
    console = MagicMock()
    engine = MagicMock()
    engine.engine_name = "Ollama"
    engine.model = "test-model"
    engine.upstream_url = "http://localhost:11434"

    with (
        patch("ai_agent.cli.llm_serve.Settings", return_value=settings),
        patch("ai_agent.cli.llm_serve.Console", return_value=console),
        patch("ai_agent.cli.llm_serve.configure_logging"),
        patch("ai_agent.cli.llm_serve.configure_stdio_encoding"),
        patch(
            "ai_agent.cli.llm_serve.managed_engine_process",
            side_effect=_noop_managed_process,
        ),
        patch("ai_agent.cli.llm_serve.prepare_upstream", return_value=engine),
        patch("ai_agent.cli.llm_serve.serve_ready_engine", return_value=0) as serve,
    ):
        assert main() == 0
        serve.assert_called_once_with(engine, settings, console)
