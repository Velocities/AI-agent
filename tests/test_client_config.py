"""Public client configuration and the CLI that stores it."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient
from rich.console import Console

from ai_agent.api.app import create_app
from ai_agent.api.client_config import CLIENT_CONFIG_PATH
from ai_agent_cli.credentials import (
    StoredSession,
    load_conversation_id,
    load_session,
    save_conversation_id,
    save_session,
)
from ai_agent_cli.server_config import (
    ensure_server_config,
    load_server_config,
    normalize_server_url,
    set_server_url,
)
from ai_agent.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "supabase_url": "",
        "supabase_anon_key": "",
        "supabase_jwt_secret": "",
    }
    values.update(overrides)
    return Settings(**values)


def _http(payload: dict[str, str], *, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == CLIENT_CONFIG_PATH
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_client_config_returns_supabase_fields() -> None:
    app = create_app(
        _settings(
            supabase_url="https://supabase.example.com/",
            supabase_anon_key="  sb_publishable_example  ",
        )
    )
    with TestClient(app) as client:
        response = client.get(CLIENT_CONFIG_PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert isinstance(body["supabase_url"], str)
    assert isinstance(body["supabase_publishable_key"], str)
    assert body == {
        "supabase_url": "https://supabase.example.com",
        "supabase_publishable_key": "sb_publishable_example",
    }


def test_client_config_is_unavailable_without_supabase() -> None:
    app = create_app(_settings(supabase_url="https://supabase.example.com"))
    with TestClient(app) as client:
        response = client.get(CLIENT_CONFIG_PATH)
    assert response.status_code == 503


def test_normalize_server_url_keeps_the_origin_only() -> None:
    assert normalize_server_url(" https://agent.example.com/ ") == "https://agent.example.com"
    assert normalize_server_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    with pytest.raises(ValueError):
        normalize_server_url("https://agent.example.com/extra")


def test_set_server_url_persists_config_and_signs_out_on_change(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_AGENT_CONFIG_DIR", str(tmp_path))
    save_session(StoredSession("access", "refresh", time.time() + 3600))
    save_conversation_id("chat-1")
    first = _http(
        {
            "supabase_url": "https://supabase.example.com",
            "supabase_publishable_key": "sb_publishable_one",
        }
    )
    created = set_server_url("https://agent.example.com/", client=first)
    assert created.signed_out is False
    assert load_session() is not None
    assert load_conversation_id() == "chat-1"
    saved = load_server_config()
    assert saved is not None
    assert saved.server_url == "https://agent.example.com"
    assert saved.supabase_url == "https://supabase.example.com"
    assert saved.supabase_publishable_key == "sb_publishable_one"

    same = set_server_url("https://agent.example.com", client=first)
    assert same.signed_out is False
    assert load_session() is not None

    changed = set_server_url(
        "https://other.example.com",
        client=_http(
            {
                "supabase_url": "https://other.supabase.example.com",
                "supabase_publishable_key": "sb_publishable_two",
            }
        ),
    )
    assert changed.signed_out is True
    assert load_session() is None
    assert load_conversation_id() is None
    assert load_server_config() is not None
    assert load_server_config().server_url == "https://other.example.com"


def test_ensure_server_config_does_not_prompt_once_saved(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_AGENT_CONFIG_DIR", str(tmp_path))
    set_server_url(
        "http://127.0.0.1:8000",
        client=_http(
            {
                "supabase_url": "https://supabase.example.com",
                "supabase_publishable_key": "sb_publishable_one",
            }
        ),
    )
    found = ensure_server_config(Console(quiet=True))
    assert found is not None
    assert found.server_url == "http://127.0.0.1:8000"
