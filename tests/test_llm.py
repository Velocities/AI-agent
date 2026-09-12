from unittest.mock import MagicMock

from ai_agent.config import LlmTransport, Settings
from ai_agent.llm import LLMProvider, OllamaProvider, create_llm_provider
from ai_agent.llm.client.types import LLMHealthcheck
from ai_agent.llm.http.errors import LLMErrorKind
from ai_agent.llm.http.session import LlmHttpSession, LlmSessionError


def test_factory_returns_provider_interface() -> None:
    settings = Settings()
    settings.ollama_transport = LlmTransport.HTTP
    provider = create_llm_provider(settings)
    try:
        assert isinstance(provider, LLMProvider)
        assert isinstance(provider, OllamaProvider)
        assert provider.endpoint == settings.llm_host.rstrip("/")
    finally:
        provider.close()


def test_healthcheck_is_on_provider_interface() -> None:
    assert "healthcheck" in LLMProvider.__abstractmethods__


def test_session_maps_connect_error(monkeypatch) -> None:
    class _FailingClient:
        def get(self, url, timeout=None):
            raise __import__("httpx").ConnectError("refused")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "ai_agent.llm.http.session.httpx.Client",
        lambda timeout: _FailingClient(),
    )
    session = LlmHttpSession("http://127.0.0.1:9")
    try:
        session.get_json("/api/tags", timeout=0.1)
    except LlmSessionError as exc:
        assert exc.kind == LLMErrorKind.UNAVAILABLE
        assert "unavailable" in exc.message
    else:
        raise AssertionError("expected LlmSessionError")
    finally:
        session.close()


def _provider_with_session(session) -> OllamaProvider:
    return OllamaProvider(session, "test-model")


def test_healthcheck_maps_session_unavailable() -> None:
    session = MagicMock()
    session.get_json.side_effect = LlmSessionError(
        LLMErrorKind.UNAVAILABLE,
        "LLM endpoint is unavailable: http://127.0.0.1:9",
    )
    session.base_url = "http://127.0.0.1:9"
    result = _provider_with_session(session).healthcheck()
    assert result == LLMHealthcheck(
        ok=False,
        message="LLM endpoint is unavailable: http://127.0.0.1:9",
        error_kind=LLMErrorKind.UNAVAILABLE,
    )


def test_healthcheck_reports_missing_model() -> None:
    session = MagicMock()
    session.get_json.side_effect = [
        {"engine": "Ollama", "model": "test-model", "upstream": "http://localhost:11434"},
        {"models": [{"name": "other:latest"}]},
    ]
    session.base_url = "http://localhost:11434"
    result = _provider_with_session(session).healthcheck()
    assert result.ok is False
    assert result.error_kind == LLMErrorKind.MODEL_NOT_FOUND
    assert "test-model" in result.message
    assert "ModelMissingError" in result.message


def test_healthcheck_reports_protocol_error() -> None:
    session = MagicMock()
    session.get_json.side_effect = [
        {"engine": "Ollama", "model": "test-model", "upstream": "http://localhost:11434"},
        ["not", "an", "object"],
    ]
    result = _provider_with_session(session).healthcheck()
    assert result.ok is False
    assert result.error_kind == LLMErrorKind.PROTOCOL


def test_healthcheck_ok_when_model_present() -> None:
    session = MagicMock()
    session.get_json.side_effect = [
        {"engine": "Ollama", "model": "test-model", "upstream": "http://localhost:11434"},
        {"models": [{"name": "test-model:latest"}]},
    ]
    result = _provider_with_session(session).healthcheck()
    assert result.ok is True
    assert result.error_kind is None
