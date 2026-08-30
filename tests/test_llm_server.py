import json
import threading
from contextlib import contextmanager
from unittest.mock import MagicMock

import httpx

from ai_agent.config import Settings
from ai_agent.llm.factory import create_llm_provider, create_upstream_provider
from ai_agent.llm.ollama import OllamaProvider
from ai_agent.llm.server import LlmFacade, bind_llm_server, public_url
from ai_agent.llm.session import LlmHttpSession, LlmSessionError
from ai_agent.llm.base import LLMErrorKind, LLMMessage


def test_public_url_rewrites_wildcard_binds() -> None:
    assert public_url("0.0.0.0", 1234) == "http://127.0.0.1:1234"
    assert public_url("127.0.0.1", 1234) == "http://127.0.0.1:1234"


def test_factory_upstream_ignores_ollama_host() -> None:
    settings = Settings()
    settings.ollama_host = "http://127.0.0.1:9"
    settings.ollama_upstream = "http://localhost:11434"
    provider = create_upstream_provider(settings)
    try:
        assert provider.endpoint == "http://localhost:11434"
        agent_provider = create_llm_provider(settings)
        try:
            assert agent_provider.endpoint == "http://127.0.0.1:9"
        finally:
            agent_provider.close()
    finally:
        provider.close()


@contextmanager
def _running_facade(session):
    httpd = bind_llm_server("127.0.0.1", 0, LlmFacade(session))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    try:
        yield public_url(str(host), int(port))
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        httpd.server_close()


def test_facade_forwards_tags() -> None:
    session = MagicMock()
    session.base_url = "http://upstream:11434"
    session.get_json.return_value = {"models": [{"name": "test-model"}]}
    with _running_facade(session) as url:
        response = httpx.get(f"{url}/api/tags", timeout=2.0)
    assert response.status_code == 200
    assert response.json()["models"][0]["name"] == "test-model"


def test_facade_health_lists_upstream() -> None:
    session = MagicMock()
    session.base_url = "http://localhost:11434"
    with _running_facade(session) as url:
        response = httpx.get(f"{url}/health", timeout=2.0)
    assert response.json() == {"status": "ok", "upstream": "http://localhost:11434"}


def test_agent_provider_can_chat_through_facade() -> None:
    chunk = json.dumps(
        {
            "model": "test-model",
            "message": {"role": "assistant", "content": "ready"},
            "done": True,
            "done_reason": "stop",
        }
    )

    class _UpstreamStream:
        def iter_lines(self):
            yield chunk

    @contextmanager
    def _stream_post(path, payload):
        assert path == "/api/chat"
        assert payload["stream"] is True
        yield _UpstreamStream()

    session = MagicMock()
    session.base_url = "http://upstream:11434"
    session.get_json.return_value = {"models": [{"name": "test-model"}]}
    session.stream_post.side_effect = _stream_post

    with _running_facade(session) as url:
        provider = OllamaProvider(LlmHttpSession(url, timeout=5.0), "test-model")
        try:
            health = provider.healthcheck()
            assert health.ok is True
            response = provider.chat([LLMMessage(role="user", content="hello")])
        finally:
            provider.close()

    assert response.error is None
    assert response.message.content == "ready"


def test_facade_maps_upstream_connect_failure() -> None:
    session = MagicMock()
    session.base_url = "http://upstream:11434"
    session.get_json.side_effect = LlmSessionError(
        LLMErrorKind.UNAVAILABLE,
        "LLM endpoint is unavailable: http://upstream:11434",
    )
    with _running_facade(session) as url:
        response = httpx.get(f"{url}/api/tags", timeout=2.0)
    assert response.status_code == 502
    assert "unavailable" in response.json()["error"]
