"""The API must never run a turn without mapping the user to a Linux account.

`build_api_agent_factory` is what binds an authenticated API user to the Linux
account an administrator approved for them. If a turn can run without it, every
user's commands execute as the service account instead.
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ai_agent.agent.loop import AgentRunResult
from ai_agent.api.agent_factory import build_api_agent_factory
from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
from ai_agent.api.turns import AGENT_FACTORY_MISSING_MESSAGE, iter_turn_events
from ai_agent.config import Settings
from ai_agent.conversations.db import open_stores_at
from ai_agent.deployment.access import (
    ACCESS_DENIED_CODE,
    ACCESS_INCOMPLETE_CODE,
    ACCESS_PENDING_CODE,
)
from ai_agent.llm.base import LLMMessage

ALICE = "11111111-1111-4111-8111-111111111111"


class _Tokens:
    def verify(self, token: str) -> AuthenticatedUser:
        if token != "alice":
            raise InvalidTokenError("no")
        return AuthenticatedUser(user_id=ALICE)


class _FakeAgent:
    def __init__(self, **_kwargs) -> None:
        self.messages: list[LLMMessage] = []
        self.on_message = None
        self.should_stop = None
        self.llm = None

    def run(self, content: str, stream_callback=None, **_kwargs) -> AgentRunResult:
        user = LLMMessage(role="user", content=content)
        self.messages.append(user)
        if self.on_message is not None:
            self.on_message(user)
        if stream_callback is not None:
            stream_callback("Hello")
        reply = LLMMessage(role="assistant", content="Hello")
        self.messages.append(reply)
        if self.on_message is not None:
            self.on_message(reply)
        return AgentRunResult(final_message="Hello", iterations=1)


def _settings() -> Settings:
    return Settings(supabase_url="", supabase_anon_key="", supabase_jwt_secret="")


@pytest.fixture
def spy(monkeypatch):
    """Capture build_agent kwargs; recording that it was never called matters."""
    calls: list[dict] = []

    def capture(**kwargs):
        calls.append(kwargs)
        return _FakeAgent()

    monkeypatch.setattr("ai_agent.api.agent_factory.build_agent", capture)
    return calls


def _stores(tmp_path, name="api.sqlite3"):
    path = tmp_path / name
    store, access = open_stores_at(f"sqlite:///{path}")
    return store, access, path


def _strip_linux_username(path) -> None:
    """Recreate a row approved before migration 0003 added linux_username.

    `approve()` refuses to leave the column empty, but 0003 backfilled existing
    rows with "", so upgraded deployments really do hold approved-but-unmapped
    users. This is the state access_incomplete exists to catch.
    """
    con = sqlite3.connect(path)
    with con:
        con.execute(
            "update deployment_access set linux_username = '' where user_id = ?",
            (ALICE,),
        )
    con.close()


def _app(tmp_path, access, store, *, wire_factory=True):
    app = create_app(_settings(), _Tokens(), store=store, access_store=access)
    if wire_factory:
        app.state.agent_factory = build_api_agent_factory(access)
    return app


def _auth(client, store, *, token="alice"):
    conversation = store.create_conversation(ALICE)
    return conversation.id, {"Authorization": f"Bearer {token}"}


# --- the factory's mapping itself -------------------------------------------


def test_approved_user_maps_to_their_linux_account(tmp_path, spy) -> None:
    _store, access, _path = _stores(tmp_path)
    access.approve(ALICE, linux_username="deployuser")

    factory = build_api_agent_factory(access)
    settings = _settings()
    factory(settings=settings, prompter=None, session=None, audit_user=ALICE)

    assert spy[0]["run_as_linux_user"] == "deployuser"
    assert spy[0]["settings"].agent_scratch_dir == settings.agent_scratch_dir / "deployuser"


def test_scratch_dir_is_not_shared_between_users(tmp_path, spy) -> None:
    _store, access, _path = _stores(tmp_path)
    other = "22222222-2222-4222-8222-222222222222"
    access.approve(ALICE, linux_username="alice_unix")
    access.approve(other, linux_username="bob_unix")
    factory = build_api_agent_factory(access)

    factory(settings=_settings(), prompter=None, session=None, audit_user=ALICE)
    factory(settings=_settings(), prompter=None, session=None, audit_user=other)

    assert spy[0]["settings"].agent_scratch_dir != spy[1]["settings"].agent_scratch_dir


def test_unapproved_user_is_never_given_a_linux_account(tmp_path, spy) -> None:
    """The factory refuses to map; the route gate is what blocks the request."""
    _store, access, _path = _stores(tmp_path)
    factory = build_api_agent_factory(access)

    factory(settings=_settings(), prompter=None, session=None, audit_user=ALICE)

    assert spy[0]["run_as_linux_user"] is None


# --- no factory means no turn -----------------------------------------------


def test_iter_turn_events_fails_closed_without_a_factory(tmp_path, spy) -> None:
    store, _access, _path = _stores(tmp_path)
    conversation = store.create_conversation(ALICE)

    events = [
        json.loads(line)
        for line in iter_turn_events(
            settings=_settings(),
            store=store,
            broker=create_app(_settings()).state.broker,
            sessions={},
            user_id=ALICE,
            conversation_id=conversation.id,
            content="whoami",
            agent_factory=None,
        )
    ]

    assert [e["type"] for e in events] == ["error"]
    assert spy == []


def test_start_turn_returns_503_without_a_factory(tmp_path, spy) -> None:
    store, access, _path = _stores(tmp_path)
    access.approve(ALICE, linux_username="deployuser")
    app = _app(tmp_path, access, store, wire_factory=False)
    client = TestClient(app)
    conversation_id, headers = _auth(client, store)

    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"content": "whoami"},
        headers=headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == AGENT_FACTORY_MISSING_MESSAGE
    assert spy == []


def test_refused_turn_leaves_the_conversation_usable(tmp_path, spy) -> None:
    """A 503 must not leave the broker holding the conversation."""
    store, access, _path = _stores(tmp_path)
    access.approve(ALICE, linux_username="deployuser")
    app = _app(tmp_path, access, store, wire_factory=False)
    client = TestClient(app)
    conversation_id, headers = _auth(client, store)
    body = {"content": "whoami"}

    assert client.post(
        f"/api/conversations/{conversation_id}/turns", json=body, headers=headers
    ).status_code == 503

    app.state.agent_factory = build_api_agent_factory(access)
    retry = client.post(
        f"/api/conversations/{conversation_id}/turns", json=body, headers=headers
    )

    assert retry.status_code == 200


# --- the access gate blocks unmapped users before the agent is built ---------


def _approved_but_unmapped(access, path) -> None:
    access.approve(ALICE, linux_username="deployuser")
    _strip_linux_username(path)


@pytest.mark.parametrize(
    "setup, code",
    [
        (_approved_but_unmapped, ACCESS_INCOMPLETE_CODE),
        (lambda access, path: None, ACCESS_PENDING_CODE),
        (lambda access, path: access.deny(ALICE), ACCESS_DENIED_CODE),
    ],
    ids=["approved-without-linux-user", "pending", "denied"],
)
def test_turn_is_refused_when_the_user_has_no_linux_mapping(
    tmp_path, spy, setup, code
) -> None:
    store, access, path = _stores(tmp_path)
    setup(access, path)
    client = TestClient(_app(tmp_path, access, store))
    conversation_id, headers = _auth(client, store)

    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"content": "whoami"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == code
    assert spy == []


# --- the approved path still works, and carries the mapping ------------------


def test_approved_turn_runs_as_the_approved_linux_user(tmp_path, spy) -> None:
    store, access, _path = _stores(tmp_path)
    access.approve(ALICE, linux_username="deployuser")
    client = TestClient(_app(tmp_path, access, store))
    conversation_id, headers = _auth(client, store)

    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"content": "whoami"},
        headers=headers,
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert any(e["type"] == "done" for e in events)
    assert len(spy) == 1
    assert spy[0]["run_as_linux_user"] == "deployuser"
    assert spy[0]["audit_user"] == ALICE
