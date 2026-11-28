"""Discord bot state, sign-in, queue, and chat commands."""

from __future__ import annotations

import asyncio
import stat
import time
from pathlib import Path

import httpx
import pytest

from ai_agent_cli.client_state import StoredSession
from ai_agent_cli.login import authorize_url, pkce_pair
from ai_agent_client.api import AgentApiError
from ai_agent_discord.chat import (
    ChatProblem,
    TurnText,
    bind_conversation,
    continue_chat,
    forget_deployment,
    list_chats,
    message_for_bot,
    parse_workflow_argument,
    use_deployment,
    workflow_command,
    workflow_gate,
)
from ai_agent_discord.config import load_config, redirect_url
from ai_agent_discord.oauth import (
    LoginBroker,
    OAuthServer,
    discord_user_id_from_token,
)
from ai_agent_discord.present import decisions_for, explain_unreachable, explain_wait, pages
from ai_agent_discord.queue import DeploymentQueue
from ai_agent_discord.store import Deployment, UserStore

ALICE = 1001
BOB = 1002
ORIGIN = "https://agent.example.com"
OTHER = "https://other.example.com"


class _Config:
    def __init__(self, url: str, supabase: str = "https://proj.supabase.co", key: str = "publishable"):
        self.server_url = url
        self.supabase_url = supabase
        self.supabase_publishable_key = key


def _jwt(discord_id: str) -> str:
    import base64
    import json

    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = json.dumps({"user_metadata": {"provider_id": discord_id}}).encode()
    payload = base64.urlsafe_b64encode(body).rstrip(b"=").decode()
    return f"{header}.{payload}."


def _store(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path / "state.json")


def _deployment(url: str = ORIGIN, conversation_id: str | None = None) -> Deployment:
    return Deployment(
        server_url=url,
        supabase_url="https://proj.supabase.co",
        supabase_publishable_key="publishable",
        conversation_id=conversation_id,
    )


def test_authorize_url_carries_state() -> None:
    _verifier, challenge = pkce_pair()
    url = authorize_url(
        supabase_url="https://proj.supabase.co",
        anon_key="publishable",
        redirect_to="https://bot.example.com/callback",
        challenge=challenge,
        state="bind-this-user",
    )
    assert "state=bind-this-user" in url
    assert "provider=discord" in url


def test_redirect_url_is_the_origin_plus_callback() -> None:
    assert redirect_url("https://bot.example.com/") == "https://bot.example.com/callback"
    with pytest.raises(ValueError):
        redirect_url("https://bot.example.com/discord")


def test_load_config_requires_token_and_public_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
        load_config({})
    with pytest.raises(ValueError, match="DISCORD_PUBLIC_URL"):
        load_config({"DISCORD_BOT_TOKEN": "token"})
    config = load_config(
        {
            "DISCORD_BOT_TOKEN": "token",
            "DISCORD_PUBLIC_URL": "https://bot.example.com",
            "AI_AGENT_DISCORD_STATE": str(tmp_path / "state.json"),
            "DISCORD_GUILD_ID": "42",
        }
    )
    assert config.oauth_port == 53683
    assert config.guild_id == 42
    assert config.state_path == tmp_path / "state.json"


def test_each_discord_user_keeps_their_own_deployment_and_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_deployment(ALICE, _deployment(ORIGIN, "alice-chat"))
    store.save_deployment(BOB, _deployment(OTHER, "bob-chat"))
    store.save_session(
        ALICE,
        ORIGIN,
        StoredSession("alice-access", "alice-refresh", time.time() + 3600),
    )
    assert store.active_deployment(ALICE).server_url == ORIGIN
    assert store.active_deployment(ALICE).conversation_id == "alice-chat"
    assert store.active_deployment(BOB).conversation_id == "bob-chat"
    assert store.session_for(BOB, ORIGIN) is None
    assert store.session_for(ALICE, ORIGIN).access_token == "alice-access"
    mode = (tmp_path / "state.json").stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_use_and_remove_deployment_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    seen: list[str] = []

    def fetch(url: str, client=None):
        seen.append(url)
        if url == OTHER:
            raise httpx.ConnectError("connection refused")
        return _Config(url)

    reply = use_deployment(store, ALICE, "https://agent.example.com/", fetch=fetch)
    assert reply.deployment == ORIGIN
    assert "Not signed in" in reply.text
    assert seen == [ORIGIN]
    store.save_session(
        ALICE,
        ORIGIN,
        StoredSession("access", "refresh", time.time() + 3600),
    )
    store.set_conversation(ALICE, ORIGIN, "from-phone")
    again = use_deployment(store, ALICE, ORIGIN, fetch=fetch)
    assert "Not signed in" not in again.text
    assert store.active_deployment(ALICE).conversation_id == "from-phone"

    with pytest.raises(ChatProblem, match="unreachable") as caught:
        use_deployment(store, ALICE, OTHER, fetch=fetch)
    assert caught.value.deployment == OTHER
    assert store.active_deployment(ALICE).server_url == ORIGIN

    use_deployment(store, ALICE, "https://second.example.com", fetch=fetch)
    removed = forget_deployment(store, ALICE, "https://second.example.com")
    assert removed.deployment == ORIGIN
    assert store.find(ALICE, "https://second.example.com") is None
    assert store.session_for(ALICE, ORIGIN) is not None


def test_supabase_change_drops_the_saved_sign_in(tmp_path: Path) -> None:
    store = _store(tmp_path)
    use_deployment(store, ALICE, ORIGIN, fetch=lambda url, client=None: _Config(url))
    store.save_session(ALICE, ORIGIN, StoredSession("access", "refresh", time.time() + 60))
    store.set_conversation(ALICE, ORIGIN, "chat-1")

    def fetch(url: str, client=None):
        return _Config(url, supabase="https://other.supabase.co", key="new-key")

    use_deployment(store, ALICE, ORIGIN, fetch=fetch)
    assert store.session_for(ALICE, ORIGIN) is None
    assert store.active_deployment(ALICE).conversation_id is None


def test_login_saves_only_the_matching_discord_account(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_deployment(ALICE, _deployment())
    sessions: list[StoredSession] = []

    def exchange(*, supabase_url, anon_key, code, verifier, client=None):
        discord_id = "1001" if code == "alice-code" else "9999"
        return StoredSession(_jwt(discord_id), "refresh", time.time() + 3600)

    broker = LoginBroker(
        store,
        redirect_url="https://bot.example.com/callback",
        exchange=exchange,
    )
    url = broker.begin(ALICE, _deployment())
    assert "state=" in url
    state = url.split("state=", 1)[1].split("&", 1)[0]
    mismatch = broker.complete({"code": ["bob-code"], "state": [state]})
    assert "does not match" in mismatch
    assert store.session_for(ALICE, ORIGIN) is None

    url = broker.begin(ALICE, _deployment())
    state = url.split("state=", 1)[1].split("&", 1)[0]
    matched = broker.complete({"code": ["alice-code"], "state": [state]})
    assert "Signed in" in matched
    saved = store.session_for(ALICE, ORIGIN)
    assert saved is not None
    sessions.append(saved)
    assert discord_user_id_from_token(saved.access_token) == "1001"


def test_oauth_callback_http(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_deployment(ALICE, _deployment())

    def exchange(*, supabase_url, anon_key, code, verifier, client=None):
        return StoredSession(_jwt(str(ALICE)), "refresh", time.time() + 3600)

    broker = LoginBroker(store, redirect_url="http://127.0.0.1/callback", exchange=exchange)
    url = broker.begin(ALICE, _deployment())
    state = url.split("state=", 1)[1].split("&", 1)[0]
    server = OAuthServer(broker, "127.0.0.1", 0)
    server.start()
    try:
        response = httpx.get(
            f"http://127.0.0.1:{server.port}/callback",
            params={"code": "ok", "state": state},
        )
    finally:
        server.close()
    assert response.status_code == 200
    assert "Signed in" in response.text
    assert store.session_for(ALICE, ORIGIN) is not None


def test_message_addressing_ignores_channel_chatter() -> None:
    assert (
        message_for_bot(
            is_dm=False,
            mentions_bot=False,
            replies_to_bot=False,
            content="hello team",
            bot_id=50,
            has_images=False,
        )
        is None
    )
    assert (
        message_for_bot(
            is_dm=False,
            mentions_bot=True,
            replies_to_bot=False,
            content="<@50> what is listening on port 80?",
            bot_id=50,
            has_images=False,
        )
        == "what is listening on port 80?"
    )
    assert (
        message_for_bot(
            is_dm=True,
            mentions_bot=False,
            replies_to_bot=False,
            content="hello",
            bot_id=50,
            has_images=False,
        )
        == "hello"
    )
    assert (
        message_for_bot(
            is_dm=False,
            mentions_bot=True,
            replies_to_bot=False,
            content="<@!50>",
            bot_id=50,
            has_images=True,
        )
        == ""
    )


def test_resume_uses_the_newest_chat_when_none_is_saved(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_deployment(ALICE, _deployment())

    class Client:
        def get_conversation(self, conversation_id):
            if conversation_id == "gone":
                raise AgentApiError(404, "Conversation not found.")
            return {"id": conversation_id, "title": "Kept"}

        def list_conversations(self):
            return [{"id": "from-phone", "title": "Phone chat"}]

        def create_conversation(self, title="", workflow=None, parameters=None):
            return {"id": "created", "title": title}

    conversation_id, notice = bind_conversation(Client(), store, ALICE, _deployment())
    assert conversation_id == "from-phone"
    assert notice == "Resuming Phone chat."
    assert store.active_deployment(ALICE).conversation_id == "from-phone"

    conversation_id, notice = bind_conversation(
        Client(),
        store,
        ALICE,
        _deployment(conversation_id="gone"),
    )
    assert conversation_id == "from-phone"
    assert "Resuming" in notice


def test_list_chats_returns_rows_for_the_signed_in_user(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.save_deployment(ALICE, _deployment(conversation_id="from-phone"))
    store.save_session(ALICE, ORIGIN, StoredSession("access", "refresh", time.time() + 3600))

    class Client:
        def __init__(self, base_url, access_token):
            assert access_token == "access"
            assert base_url == ORIGIN

        def list_conversations(self):
            return [{"id": "from-phone", "title": "Phone chat", "workflow": {}}]

        def close(self):
            return None

    monkeypatch.setattr("ai_agent_discord.chat.AgentApiClient", Client)
    reply = list_chats(store, ALICE)
    assert reply.deployment == ORIGIN
    assert reply.conversations[0]["id"] == "from-phone"
    assert "Phone chat" in reply.text
    assert "*" in reply.text


def test_continue_chat_switches_the_saved_id(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.save_deployment(ALICE, _deployment(conversation_id="current"))
    store.save_session(ALICE, ORIGIN, StoredSession("access", "refresh", time.time() + 3600))

    class Client:
        def __init__(self, base_url, access_token):
            pass

        def get_conversation(self, conversation_id):
            assert conversation_id == "older"
            return {"id": "older", "title": "Older chat"}

        def close(self):
            return None

    monkeypatch.setattr("ai_agent_discord.chat.AgentApiClient", Client)
    reply = continue_chat(store, ALICE, "older")
    assert reply.text == "Continuing Older chat."
    assert store.active_deployment(ALICE).conversation_id == "older"


def test_workflow_requires_parameters_and_parses_pairs(tmp_path: Path, monkeypatch) -> None:
    assert parse_workflow_argument("fetch url=https://example.com extra") == (
        "fetch",
        {"url": "https://example.com"},
    )
    store = _store(tmp_path)
    store.save_deployment(ALICE, _deployment())
    store.save_session(ALICE, ORIGIN, StoredSession("access", "refresh", time.time() + 3600))
    catalog = [
        {
            "name": "fetch",
            "description": "Fetch pages",
            "parameters": [{"name": "url", "required": True, "description": "Page"}],
        }
    ]

    class Client:
        def __init__(self, base_url, access_token):
            pass

        def list_workflows(self):
            return catalog

        def create_conversation(self, title="", workflow=None, parameters=None):
            assert workflow == "fetch"
            assert parameters == {"url": "https://example.com"}
            return {
                "id": "wf1",
                "title": title,
                "workflow": {"name": "fetch", "status": "is_ready"},
            }

        def close(self):
            return None

    monkeypatch.setattr("ai_agent_discord.chat.AgentApiClient", Client)
    missing = workflow_command(store, ALICE, "fetch")
    assert "url" in missing.text
    started = workflow_command(store, ALICE, "fetch url=https://example.com")
    assert "Started workflow fetch" in started.text
    assert store.active_deployment(ALICE).conversation_id == "wf1"
    assert workflow_gate({"workflow": {"status": "is_building"}})
    assert workflow_gate({"workflow": {"status": "is_ready"}}) is None


def test_turn_text_keeps_tokens_notices_and_errors() -> None:
    text = TurnText()
    assert text.feed({"type": "token", "text": "Hel"}) is None
    assert text.feed({"type": "token", "text": "lo"}) is None
    assert text.feed({"type": "notice", "text": "running uname"}) is None
    assert text.finish() == "Hello\n· running uname"
    failed = TurnText()
    assert failed.feed({"type": "error", "message": "Turn failed."}) == "Turn failed."


def test_wait_copy_and_unreachable_name_the_situation() -> None:
    assert "1 person is ahead" in explain_wait(1)
    assert "2 people are ahead" in explain_wait(2)
    text = explain_unreachable("https://agent.example.com", ConnectionError("timed out"))
    assert "https://agent.example.com" in text
    assert "unreachable" in text
    long = "word " * 2000
    assert "".join(pages(long, limit=1000)).strip() == long.strip()
    assert decisions_for([{}, {}], {2}) == [
        {"id": 1, "decision": "reject"},
        {"id": 2, "decision": "accept"},
    ]


@pytest.mark.asyncio
async def test_queue_is_per_deployment_and_pings_the_waiter() -> None:
    queue = DeploymentQueue()
    first = await queue.join(ORIGIN)
    second = await queue.join(ORIGIN)
    other = await queue.join(OTHER)
    assert first.ahead == 0
    assert second.ahead == 1
    assert other.ahead == 0
    await first.wait()
    await other.wait()
    waiting = asyncio.create_task(second.wait())
    await asyncio.sleep(0.05)
    assert not waiting.done()
    await first.close()
    await asyncio.wait_for(waiting, timeout=1)
    await second.close()
    await other.close()

    abandoned = await queue.join(ORIGIN)
    assert abandoned.ahead == 0
    await abandoned.close()
    nxt = await queue.join(ORIGIN)
    assert nxt.ahead == 0
    await nxt.close()
