"""Public client configuration and the CLI that stores it."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient
from rich.console import Console

from ai_agent.api.app import create_app
from ai_agent.api.client_config import CLIENT_CONFIG_PATH
from ai_agent_cli.client_state import (
    StoredSession,
    load_conversation_id,
    load_session,
    load_session_for,
    save_conversation_id,
    save_session,
    save_session_for,
)
from ai_agent_cli.server_config import (
    ensure_server_config,
    list_servers,
    load_server_config,
    normalize_server_url,
    remove_server,
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


def test_servers_keep_separate_sessions(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_AGENT_CONFIG_DIR", str(tmp_path))
    first = _http(
        {
            "supabase_url": "https://supabase.example.com",
            "supabase_publishable_key": "sb_publishable_one",
        }
    )
    created = set_server_url("https://agent.example.com/", client=first)
    assert created.needs_login is True
    save_session(StoredSession("access", "refresh", time.time() + 3600))
    save_conversation_id("chat-1")
    assert load_session() is not None
    assert load_session().access_token == "access"
    assert load_conversation_id() == "chat-1"
    saved = load_server_config()
    assert saved is not None
    assert saved.server_url == "https://agent.example.com"
    assert saved.supabase_url == "https://supabase.example.com"
    assert saved.supabase_publishable_key == "sb_publishable_one"

    same = set_server_url("https://agent.example.com", client=first)
    assert same.needs_login is False
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
    assert changed.needs_login is True
    assert load_session() is None
    assert load_conversation_id() is None
    assert load_server_config() is not None
    assert load_server_config().server_url == "https://other.example.com"
    assert [server.server_url for server in list_servers()] == [
        "https://agent.example.com",
        "https://other.example.com",
    ]
    first_session = load_session_for("https://agent.example.com")
    assert first_session is not None
    assert first_session.access_token == "access"

    save_session_for(
        "https://other.example.com",
        StoredSession("other-access", "other-refresh", time.time() + 3600),
    )
    save_conversation_id("chat-2")
    switched_back = set_server_url("https://agent.example.com", client=first)
    assert switched_back.needs_login is False
    assert load_session() is not None
    assert load_session().access_token == "access"
    assert load_conversation_id() == "chat-1"
    assert load_session_for("https://other.example.com") is not None
    assert load_session_for("https://other.example.com").access_token == "other-access"


def test_supabase_change_clears_only_that_servers_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_AGENT_CONFIG_DIR", str(tmp_path))
    home = _http(
        {
            "supabase_url": "https://supabase.example.com",
            "supabase_publishable_key": "sb_publishable_one",
        }
    )
    set_server_url("https://agent.example.com", client=home)
    set_server_url(
        "https://other.example.com",
        client=_http(
            {
                "supabase_url": "https://other.supabase.example.com",
                "supabase_publishable_key": "sb_publishable_two",
            }
        ),
    )
    save_session_for(
        "https://agent.example.com",
        StoredSession("home", "home-refresh", time.time() + 3600),
    )
    save_session_for(
        "https://other.example.com",
        StoredSession("other", "other-refresh", time.time() + 3600),
    )
    updated = set_server_url(
        "https://agent.example.com",
        client=_http(
            {
                "supabase_url": "https://replaced.supabase.example.com",
                "supabase_publishable_key": "sb_publishable_replaced",
            }
        ),
    )
    assert updated.needs_login is True
    assert load_session_for("https://agent.example.com") is None
    other = load_session_for("https://other.example.com")
    assert other is not None
    assert other.access_token == "other"


def test_remove_server_deletes_its_session_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_AGENT_CONFIG_DIR", str(tmp_path))
    set_server_url(
        "https://agent.example.com",
        client=_http(
            {
                "supabase_url": "https://supabase.example.com",
                "supabase_publishable_key": "sb_publishable_one",
            }
        ),
    )
    set_server_url(
        "https://other.example.com",
        client=_http(
            {
                "supabase_url": "https://other.supabase.example.com",
                "supabase_publishable_key": "sb_publishable_two",
            }
        ),
    )
    save_session_for(
        "https://agent.example.com",
        StoredSession("home", "home-refresh", time.time() + 3600),
    )
    save_session_for(
        "https://other.example.com",
        StoredSession("other", "other-refresh", time.time() + 3600),
    )
    remaining = remove_server("https://other.example.com/")
    assert remaining is not None
    assert remaining.server_url == "https://agent.example.com"
    assert load_session_for("https://other.example.com") is None
    assert load_session() is not None
    assert load_session().access_token == "home"


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
