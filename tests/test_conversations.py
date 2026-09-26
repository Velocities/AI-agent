import json
import stat
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_agent.agent.loop import AgentRunResult
from ai_agent.api.app import create_app
from ai_agent.api.approvals import ApprovalBroker, RemoteApprovalPrompter
from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
from ai_agent.approval.session import ApprovalSession
from ai_agent.cli.credentials import StoredSession, save_session, session_path
from ai_agent.cli.login import authorize_url, exchange_code, pkce_pair
from ai_agent.commands.ast import SingleCommand
from ai_agent.config import ConfirmationMode, Settings
from ai_agent.conversations.db import open_store_at
from ai_agent.conversations.store import ConversationNotFound, InvalidMessage
from ai_agent.llm.base import LLMMessage
from ai_agent.policy.engine import PolicyDecision
from ai_agent.policy.risk import RiskLevel

ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"


class _Tokens:
    def verify(self, token: str) -> AuthenticatedUser:
        users = {"alice": ALICE, "bob": BOB}
        try:
            return AuthenticatedUser(user_id=users[token])
        except KeyError as exc:
            raise InvalidTokenError("no") from exc


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


def _client(tmp_path):
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    app = create_app(_settings(), _Tokens(), store=store)
    app.state.agent_factory = lambda **_kwargs: _FakeAgent()
    return TestClient(app), store


def test_store_keeps_messages_in_order_and_hides_other_users(tmp_path) -> None:
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    alice = store.create_conversation(ALICE)
    store.append_message(ALICE, alice.id, role="user", content="Show disk space")
    store.append_message(
        ALICE,
        alice.id,
        role="assistant",
        content="",
        metadata={"tool_calls": [{"id": "1", "name": "run_command", "arguments": {}}]},
    )
    saved = store.get_conversation(ALICE, alice.id)
    assert saved is not None
    assert saved.title == "Show disk space"
    messages = store.list_messages(ALICE, alice.id)
    assert [message.position for message in messages] == [0, 1]
    assert messages[1].metadata["tool_calls"][0]["name"] == "run_command"
    assert store.get_conversation(BOB, alice.id) is None
    assert store.list_conversations(BOB) == []
    with pytest.raises(ConversationNotFound):
        store.list_messages(BOB, alice.id)
    with pytest.raises(ConversationNotFound):
        store.append_message(BOB, alice.id, role="user", content="nope")
    with pytest.raises(InvalidMessage):
        store.append_message(ALICE, alice.id, role="system", content="hidden")


def test_conversation_routes_use_the_token_subject(tmp_path) -> None:
    client, _store = _client(tmp_path)
    headers = {"Authorization": "Bearer alice"}
    with client:
        created = client.post("/api/conversations", json={"title": ""}, headers=headers)
        assert created.status_code == 200
        conversation_id = created.json()["id"]
        rejected = client.post(
            "/api/conversations",
            json={"title": "x", "user_id": BOB},
            headers=headers,
        )
        assert rejected.status_code == 422
        missing = client.get(f"/api/conversations/{conversation_id}", headers={"Authorization": "Bearer bob"})
        assert missing.status_code == 404
        denied = client.get("/api/conversations")
        assert denied.status_code == 401


def test_turn_persists_the_transcript(tmp_path) -> None:
    client, store = _client(tmp_path)
    headers = {"Authorization": "Bearer alice"}
    with client:
        created = client.post("/api/conversations", json={}, headers=headers)
        conversation_id = created.json()["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/turns",
            json={"content": "hello"},
            headers=headers,
        )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[0] == {"type": "token", "text": "Hello"}
    assert events[-1]["type"] == "done"
    assert events[-1]["message"] == "Hello"
    messages = store.list_messages(ALICE, conversation_id)
    assert [(message.role, message.content) for message in messages] == [
        ("user", "hello"),
        ("assistant", "Hello"),
    ]


def test_approval_ignores_another_users_decision() -> None:
    broker = ApprovalBroker()
    session = ApprovalSession()
    seen: list[dict] = []
    prompter = RemoteApprovalPrompter(
        ConfirmationMode.PARANOID,
        session,
        broker,
        user_id=ALICE,
        conversation_id="chat",
        emit=seen.append,
        cancel=threading.Event(),
        timeout=5,
    )
    decision = PolicyDecision(
        expr=SingleCommand(argv=["rm", "x"]),
        effective_risk=RiskLevel.DESTRUCTIVE,
        segments=[],
        allowed=True,
        reason="remove a file",
    )

    def respond() -> None:
        while not seen:
            threading.Event().wait(0.01)
        event = seen[0]
        assert (
            broker.resolve(
                user_id=BOB,
                conversation_id="chat",
                approval_id=event["approval_id"],
                approved=True,
                grant_scope="reversible_session",
            )
            is False
        )
        assert broker.resolve(
            user_id=ALICE,
            conversation_id="chat",
            approval_id=event["approval_id"],
            approved=True,
            grant_scope="reversible_session",
        )

    threading.Thread(target=respond, daemon=True).start()
    result = prompter.prompt_single(decision, reason="remove a file")
    assert result.approved is True
    assert result.grant_scope is None
    assert session.grants == []


def test_pkce_and_private_session_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    verifier, challenge = pkce_pair()
    assert verifier
    assert "=" not in challenge
    url = authorize_url(
        supabase_url="https://proj.supabase.co/",
        anon_key="publishable",
        redirect_to="http://127.0.0.1:53682/callback",
        challenge=challenge,
    )
    assert url.startswith("https://proj.supabase.co/auth/v1/authorize?")
    assert "provider=discord" in url
    assert "127.0.0.1" in url

    def handler(request: httpx.Request) -> httpx.Response:
        assert "grant_type=pkce" in str(request.url)
        body = json.loads(request.content.decode())
        assert body["code_verifier"] == verifier
        return httpx.Response(
            200,
            json={"access_token": "access", "refresh_token": "refresh", "expires_in": 30},
        )

    session = exchange_code(
        supabase_url="https://proj.supabase.co",
        anon_key="publishable",
        code="oauth-code",
        verifier=verifier,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert session.access_token == "access"
    monkeypatch.setenv("AI_AGENT_CONFIG_DIR", str(tmp_path))
    save_session(session)
    mode = session_path().stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR
