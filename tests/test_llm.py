from ai_agent.config import Settings
from ai_agent.llm import LLMProvider, OllamaProvider, create_llm_provider
from ai_agent.llm.base import LLMErrorKind
from ai_agent.llm.session import LlmHttpSession, LlmSessionError


def test_factory_returns_provider_interface() -> None:
    settings = Settings()
    provider = create_llm_provider(settings)
    try:
        assert isinstance(provider, LLMProvider)
        assert isinstance(provider, OllamaProvider)
        assert provider.endpoint == settings.ollama_host.rstrip("/")
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
        "ai_agent.llm.session.httpx.Client",
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
