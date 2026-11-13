"""Client debug logs land in one file per user, in client order, only while the setting is on."""

from pathlib import Path

from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
from ai_agent.config import Settings
from ai_agent.conversations.client_logs import ClientLogBatch, ClientLogWriter
from ai_agent.conversations.db import open_store_at

ALICE = "11111111-1111-4111-8111-111111111111"
HEADERS = {"Authorization": "Bearer alice"}


class _Tokens:
    def verify(self, token: str) -> AuthenticatedUser:
        if token != "alice":
            raise InvalidTokenError("no")
        return AuthenticatedUser(user_id=ALICE)


def _client(tmp_path: Path) -> TestClient:
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    settings = Settings(CLIENT_LOG_ROOT=str(tmp_path / "logs"))
    return TestClient(create_app(settings, _Tokens(), store=store))


def _batch(first: int, *lines: str) -> dict:
    return {"stream": "abc-1", "device": "Pixel 9", "first_seq": first, "lines": list(lines)}


def test_upload_is_refused_until_debug_logging_is_on(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        refused = client.post("/api/me/client-logs", headers=HEADERS, json=_batch(0, "a"))
        turned_on = client.patch(
            "/api/me/settings", headers=HEADERS, json={"client_debug_logging": True}
        )
        accepted = client.post("/api/me/client-logs", headers=HEADERS, json=_batch(0, "a", "b"))
        kept = client.patch("/api/me/settings", headers=HEADERS, json={"agent_name": ""})
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "debug_logging_off"
    assert turned_on.json()["client_debug_logging"] is True
    assert accepted.json() == {"next_seq": 2}
    assert kept.json()["client_debug_logging"] is True
    log = (tmp_path / "logs" / ALICE / "client.log").read_text().splitlines()
    assert log == ["----- client abc-1 (Pixel 9) -----", "a", "b"]


def test_retries_are_written_once_and_gaps_are_marked(tmp_path: Path) -> None:
    writer = ClientLogWriter(tmp_path)
    assert writer.append(ALICE, ClientLogBatch("s1", "phone", 0, ("one", "two"))) == 2
    # The acknowledgement was lost and the client sent the same batch plus a new line.
    assert writer.append(ALICE, ClientLogBatch("s1", "phone", 0, ("one", "two", "three"))) == 3
    assert writer.append(ALICE, ClientLogBatch("s1", "phone", 1, ("two",))) == 3
    # The client dropped seq 3 and 4 when its buffer overflowed.
    assert writer.append(ALICE, ClientLogBatch("s1", "phone", 5, ("six",))) == 6
    assert writer.append(ALICE, ClientLogBatch("s2", "phone", 0, ("new process",))) == 1
    assert writer.append(ALICE, ClientLogBatch("s2", "phone", 1, ("multi\nline",))) == 2
    lines = (tmp_path / ALICE / "client.log").read_text().splitlines()
    assert lines == [
        "----- client s1 (phone) -----",
        "one",
        "two",
        "three",
        "[2 client log lines were dropped before they were sent]",
        "six",
        "----- client s2 (phone) -----",
        "new process",
        "multi\\nline",
    ]


def test_unsafe_ids_are_refused(tmp_path: Path) -> None:
    writer = ClientLogWriter(tmp_path)
    for stream in ("../x", "", "a/b"):
        try:
            writer.append(ALICE, ClientLogBatch(stream, "phone", 0, ("x",)))
        except ValueError:
            continue
        raise AssertionError(f"{stream!r} was accepted")
