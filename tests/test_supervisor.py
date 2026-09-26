import socket
import threading
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from ai_agent.api.turns import _default_agent_factory, _run_turn
from ai_agent.config import LlmTransport, Settings
from ai_agent.llm.server.process.ollama import OllamaEngineProcess
from ai_agent.service.notify import sd_notify
from ai_agent.service.supervisor import run, settings_for_api


def test_settings_for_api_uses_the_facade_over_http() -> None:
    settings = Settings()
    settings.llm_transport = LlmTransport.SSH
    settings.llm_host = "http://127.0.0.1:11434"

    updated = settings_for_api(settings, "http://127.0.0.1:43111")

    assert updated.llm_host == "http://127.0.0.1:43111"
    assert updated.llm_transport == LlmTransport.HTTP
    assert settings.llm_host == "http://127.0.0.1:11434"
    assert settings.llm_transport == LlmTransport.SSH


def test_default_agent_factory_keeps_the_passed_settings(monkeypatch) -> None:
    captured: dict = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("ai_agent.api.turns.build_agent", capture)
    settings = Settings()
    _default_agent_factory(
        settings=settings,
        prompter=None,
        session=None,
        audit_user="user",
    )
    assert captured["settings"] is settings


def test_run_turn_passes_settings_into_the_factory() -> None:
    settings = Settings()
    seen: dict = {}

    def factory(**kwargs):
        seen.update(kwargs)
        agent = MagicMock()
        agent.messages = []
        agent.run.return_value = MagicMock(final_message="ok", error=None)
        return agent

    store = MagicMock()
    store.list_messages.return_value = []
    _run_turn(
        settings=settings,
        store=store,
        broker=MagicMock(),
        sessions={},
        user_id="user",
        conversation_id="conv",
        content="hi",
        emit=lambda _event: None,
        cancel=threading.Event(),
        agent_factory=factory,
    )
    assert seen["settings"] is settings


def test_sd_notify_sends_ready(tmp_path, monkeypatch) -> None:
    sock_path = tmp_path / "notify.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(str(sock_path))
    server.settimeout(1)
    monkeypatch.setenv("NOTIFY_SOCKET", str(sock_path))

    sd_notify("Listening on http://127.0.0.1:8000", ready=True)
    data, _addr = server.recvfrom(4096)
    server.close()

    assert b"READY=1\n" in data
    assert b"STATUS=Listening on http://127.0.0.1:8000\n" in data


def test_sd_notify_is_a_noop_without_systemd(monkeypatch) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    sd_notify("ignored", ready=True)


def test_subprocess_engine_inherits_stdio() -> None:
    settings = Settings()
    process = OllamaEngineProcess(settings)
    process._binary = "ollama"
    with pytest.MonkeyPatch.context() as monkeypatch:
        popen = MagicMock()
        monkeypatch.setattr(
            "ai_agent.llm.server.process.subprocess_base.subprocess.Popen",
            popen,
        )
        process._start()
    kwargs = popen.call_args.kwargs
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs
    assert kwargs["env"]["OLLAMA_HOST"]


def test_run_refuses_a_public_api_bind(monkeypatch) -> None:
    monkeypatch.setenv("API_BIND_HOST", "0.0.0.0")
    called = False

    def open_store(_settings):
        nonlocal called
        called = True
        raise AssertionError("database should not open")

    monkeypatch.setattr("ai_agent.service.supervisor.open_store", open_store)
    assert run(Settings(), MagicMock()) == 1
    assert called is False


def test_run_returns_1_when_the_database_cannot_open(monkeypatch) -> None:
    def open_store(_settings):
        raise RuntimeError("disk full")

    def managed(*_args, **_kwargs):
        raise AssertionError("engine should not start")

    monkeypatch.setattr("ai_agent.service.supervisor.open_store", open_store)
    monkeypatch.setattr("ai_agent.service.supervisor.managed_engine_process", managed)
    assert run(Settings(), MagicMock()) == 1


def test_run_returns_1_when_the_model_does_not_warm(monkeypatch) -> None:
    monkeypatch.setattr("ai_agent.service.supervisor.open_store", lambda _settings: MagicMock())
    monkeypatch.setattr(
        "ai_agent.service.supervisor.managed_engine_process",
        _attached_engine(),
    )
    monkeypatch.setattr("ai_agent.service.supervisor.prepare_upstream", lambda *_a, **_k: None)
    bind = MagicMock()
    monkeypatch.setattr("ai_agent.service.supervisor.bind_llm_server", bind)

    assert run(Settings(), MagicMock()) == 1
    bind.assert_not_called()


def test_run_points_the_api_at_the_facade_and_stops_it(monkeypatch) -> None:
    httpd = MagicMock()
    httpd.server_address = ("127.0.0.1", 43111)
    seen: dict = {}

    def run_api(api_settings, _store, _console):
        seen["host"] = api_settings.llm_host
        seen["transport"] = api_settings.llm_transport
        return 0

    monkeypatch.setattr("ai_agent.service.supervisor.open_store", lambda _settings: MagicMock())
    monkeypatch.setattr(
        "ai_agent.service.supervisor.managed_engine_process",
        _attached_engine(),
    )
    monkeypatch.setattr(
        "ai_agent.service.supervisor.prepare_upstream",
        lambda *_a, **_k: _engine(),
    )
    monkeypatch.setattr("ai_agent.service.supervisor.bind_llm_server", lambda *_a, **_k: httpd)
    monkeypatch.setattr("ai_agent.service.supervisor._run_api", run_api)

    assert run(Settings(), MagicMock()) == 0
    assert seen["host"] == "http://127.0.0.1:43111"
    assert seen["transport"] == LlmTransport.HTTP
    httpd.shutdown.assert_called_once()
    httpd.server_close.assert_called_once()


def test_run_closes_the_facade_when_the_api_exits(monkeypatch) -> None:
    httpd = MagicMock()
    httpd.server_address = ("127.0.0.1", 43111)
    engine = _engine()

    def run_api(*_args, **_kwargs):
        raise SystemExit(3)

    monkeypatch.setattr("ai_agent.service.supervisor.open_store", lambda _settings: MagicMock())
    monkeypatch.setattr(
        "ai_agent.service.supervisor.managed_engine_process",
        _attached_engine(),
    )
    monkeypatch.setattr(
        "ai_agent.service.supervisor.prepare_upstream",
        lambda *_a, **_k: engine,
    )
    monkeypatch.setattr("ai_agent.service.supervisor.bind_llm_server", lambda *_a, **_k: httpd)
    monkeypatch.setattr("ai_agent.service.supervisor._run_api", run_api)

    with pytest.raises(SystemExit) as exc:
        run(Settings(), MagicMock())
    assert exc.value.code == 3
    httpd.shutdown.assert_called_once()
    engine.close.assert_called_once()


def _engine() -> MagicMock:
    engine = MagicMock()
    engine.engine_name = "Ollama"
    engine.upstream_url = "http://127.0.0.1:11434"
    return engine


def _attached_engine():
    @contextmanager
    def managed(*_args, **_kwargs):
        process = MagicMock()
        process.upstream_url = "http://127.0.0.1:11434"
        process.started_by_us = False
        yield process

    return managed

