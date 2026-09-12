from unittest.mock import MagicMock, patch

import pytest

from ai_agent.config import LlmEngineKind, LlmTransport, Settings
from ai_agent.llm.server.process.base import EngineProcessError, ExternalEngineProcess
from ai_agent.llm.server.process.factory import create_engine_process
from ai_agent.llm.server.process.ollama import OllamaEngineProcess
from ai_agent.llm.server.process.url import normalize_upstream_url, parse_upstream_url
from ai_agent.llm.server.process.vllm import VLLMEngineProcess


def test_parse_upstream_url() -> None:
    assert parse_upstream_url("http://127.0.0.1:11434") == ("127.0.0.1", 11434)
    assert normalize_upstream_url("http://localhost:8000/v1") == "http://localhost:8000"


def test_factory_uses_external_process_for_ssh() -> None:
    settings = Settings()
    settings.llm_transport = LlmTransport.SSH
    process = create_engine_process(settings)
    assert isinstance(process, ExternalEngineProcess)


def test_factory_uses_external_process_when_manage_disabled() -> None:
    settings = Settings()
    settings.llm_manage_upstream = False
    process = create_engine_process(settings)
    assert isinstance(process, ExternalEngineProcess)


def test_factory_selects_engine_process_by_kind() -> None:
    settings = Settings()
    settings.llm_engine = LlmEngineKind.OLLAMA
    assert isinstance(create_engine_process(settings), OllamaEngineProcess)

    settings.llm_engine = LlmEngineKind.VLLM
    assert isinstance(create_engine_process(settings), VLLMEngineProcess)


def test_ollama_process_builds_serve_command() -> None:
    settings = Settings()
    settings.llm_upstream = "http://127.0.0.1:11434"
    process = OllamaEngineProcess(settings)
    process._binary = "ollama"  # bypass PATH lookup in unit test
    assert process._command() == ["ollama", "serve"]
    assert process._subprocess_env()["OLLAMA_HOST"] == "127.0.0.1:11434"


def test_vllm_process_builds_serve_command(monkeypatch) -> None:
    settings = Settings()
    settings.llm_upstream = "http://127.0.0.1:8000"
    settings.llm_model = "meta-llama/Llama-3.1-8B-Instruct"
    process = VLLMEngineProcess(settings)
    monkeypatch.setattr(
        "ai_agent.llm.server.process.vllm.shutil.which",
        lambda name: "vllm" if name == "vllm" else None,
    )
    assert process._command() == [
        "vllm",
        "serve",
        "meta-llama/Llama-3.1-8B-Instruct",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]


def test_vllm_missing_shows_install_hint_on_windows(monkeypatch) -> None:
    settings = Settings()
    monkeypatch.setattr("ai_agent.llm.server.process.vllm.sys.platform", "win32")
    monkeypatch.setattr("ai_agent.llm.server.process.vllm.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "ai_agent.llm.server.process.vllm.importlib.util.find_spec",
        lambda _name: None,
    )
    process = VLLMEngineProcess(settings)
    try:
        process._command()
    except Exception as exc:
        message = str(exc)
    else:
        raise AssertionError("expected EngineProcessError")
    assert "Could not find vLLM" in message
    assert "LLM_ENGINE=ollama" in message


def test_subprocess_process_skips_start_when_upstream_already_up() -> None:
    settings = Settings()
    process = OllamaEngineProcess(settings)
    process._binary = "ollama"
    with patch(
        "ai_agent.llm.server.process.base.wait_for_upstream",
        return_value=True,
    ) as wait:
        process.ensure_running(timeout=5.0)
    assert process.started_by_us is False
    wait.assert_called_once()


def test_subprocess_process_starts_when_upstream_is_down() -> None:
    settings = Settings()
    process = OllamaEngineProcess(settings)
    process._binary = "ollama"
    with (
        patch(
            "ai_agent.llm.server.process.base.wait_for_upstream",
            side_effect=[False, True],
        ),
        patch.object(process, "_start") as start,
        patch.object(process, "_stop"),
    ):
        process.ensure_running(timeout=5.0)
    start.assert_called_once()
    assert process.started_by_us is True


def test_external_process_fails_when_unreachable() -> None:
    settings = Settings()
    process = ExternalEngineProcess(settings, reason="test")
    with (
        patch(
            "ai_agent.llm.server.process.base.wait_for_upstream",
            return_value=False,
        ),
        pytest.raises(EngineProcessError),
    ):
        process.ensure_running(timeout=1.0)


def test_runtime_stops_managed_process_on_exit() -> None:
    from ai_agent.llm.server.runtime import managed_engine_process

    settings = Settings()
    console = MagicMock()
    console.status.return_value.__enter__.return_value = None
    console.status.return_value.__exit__.return_value = False
    process = MagicMock()
    process.engine_name = "Ollama"
    process.upstream_url = settings.llm_upstream
    process.started_by_us = True

    with patch(
        "ai_agent.llm.server.runtime.create_engine_process",
        return_value=process,
    ):
        with managed_engine_process(settings, console) as active:
            assert active is process
    process.stop.assert_called_once()
