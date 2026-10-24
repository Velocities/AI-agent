"""Replay window, budgets, cache identity, and missing blobs."""

import threading
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from ai_agent.api.transcript import message_from_record
from ai_agent.api.turns import _replay_loader
from ai_agent.attachments.cache import AttachmentCache
from ai_agent.attachments.replay import select_replay_message_ids
from ai_agent.attachments.types import checksum_bytes
from ai_agent.conversations.store import Message
from ai_agent.llm.client.types import ImageInput
from tests.test_images import ALICE, _api, png_bytes

BOB = "22222222-2222-4222-8222-222222222222"


def _record(message_id: str, *parts: tuple[str, int], kind: str = "image", role: str = "user") -> Message:
    from datetime import datetime, timezone

    return Message(
        id=message_id,
        conversation_id="conv",
        role=role,
        content="see",
        created_at=datetime.now(timezone.utc),
        metadata={
            "attachments": [
                {"kind": kind, "id": attachment_id, "media_type": "image/png", "byte_size": size}
                for attachment_id, size in parts
            ]
        },
        position=0,
    )


def test_replay_window_and_budgets() -> None:
    records = [
        _record("m1", ("a", 1)),
        _record("m2", ("b", 6_000_000)),
        _record("m3", ("c", 1_000_000)),
        _record("m4", ("d", 6_000_000)),
        _record("m5", ("e", 6_000_000)),
    ]
    chosen = select_replay_message_ids(
        records,
        current_images=1,
        current_bytes=6_000_000,
        max_messages=4,
        max_images=8,
        max_bytes=16_000_000,
    )
    assert "m1" not in chosen
    assert "m5" in chosen
    assert "m4" not in chosen
    assert "m3" in chosen
    none = select_replay_message_ids(
        records,
        current_images=0,
        current_bytes=0,
        max_messages=0,
        max_images=8,
        max_bytes=16_000_000,
    )
    assert none == set()


def test_unknown_kind_is_not_loaded() -> None:
    record = _record("m1", ("doc", 10), kind="document")
    calls: list[str] = []

    def loader(attachment_id: str) -> ImageInput | None:
        calls.append(attachment_id)
        return ImageInput(data=b"x", media_type="image/png")

    message = message_from_record(record, loader=loader, include_images=True)
    assert message.images == []
    assert calls == []
    assert record.metadata["attachments"][0]["kind"] == "document"


def test_loader_memoizes_and_skips_a_missing_file() -> None:
    class _Catalog:
        def get(self, user_id: str, attachment_id: str):
            from ai_agent.attachments.types import Attachment

            if attachment_id == "missing":
                return Attachment(
                    id=attachment_id,
                    user_id=user_id,
                    conversation_id="c",
                    kind="image",
                    media_type="image/png",
                    byte_size=1,
                    checksum="abc",
                )
            return Attachment(
                id=attachment_id,
                user_id=user_id,
                conversation_id="c",
                kind="image",
                media_type="image/png",
                byte_size=3,
                checksum=checksum_bytes(b"png"),
            )

    class _Blobs:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(self, user_id: str, attachment_id: str) -> bytes:
            self.calls.append(attachment_id)
            if attachment_id == "missing":
                from ai_agent.attachments.store import AttachmentNotFound

                raise AttachmentNotFound(attachment_id)
            return b"png"

    blobs = _Blobs()
    cache = AttachmentCache(blobs, max_bytes=100)
    loader = _replay_loader(ALICE, catalog=_Catalog(), cache=cache)
    assert loader("ok") is not None
    assert loader("ok") is not None
    assert loader("missing") is None
    assert blobs.calls == ["ok", "missing"]


def test_second_turn_replays_the_image_once(tmp_path: Path) -> None:
    client, _store, holder = _api(tmp_path)
    headers = {"Authorization": "Bearer alice"}
    png = png_bytes()
    with client:
        conversation_id = client.post("/api/conversations", json={}, headers=headers).json()["id"]
        first = client.post(
            f"/api/conversations/{conversation_id}/turns",
            data={"content": "Look"},
            files=[("images", ("shot.png", png, "image/png"))],
            headers=headers,
        )
        assert first.status_code == 200
        blobs = client.app.state.attachment_store
        calls: list[str] = []
        original = blobs.get

        def spy(user_id: str, attachment_id: str) -> bytes:
            calls.append(attachment_id)
            return original(user_id, attachment_id)

        blobs.get = spy
        second = client.post(
            f"/api/conversations/{conversation_id}/turns",
            json={"content": "And now?"},
            headers=headers,
        )
    assert second.status_code == 200
    history = [message for message in holder["agent"].messages if message.role == "user"]
    assert history[0].images
    assert history[0].images[0].media_type == "image/png"
    assert calls.count(history[0].images[0].attachment_id) == 1


def test_cross_user_conversation_is_not_found(tmp_path: Path) -> None:
    from ai_agent.api.app import create_app
    from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
    from ai_agent.config import Settings
    from ai_agent.conversations.db import open_store_at

    class _Tokens:
        def verify(self, token: str) -> AuthenticatedUser:
            users = {"alice": ALICE, "bob": BOB}
            if token not in users:
                raise InvalidTokenError("no")
            return AuthenticatedUser(user_id=users[token])

    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    app = create_app(Settings(), _Tokens(), store=store)
    headers = {"Authorization": "Bearer alice"}
    bob = {"Authorization": "Bearer bob"}
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}, headers=headers).json()["id"]
        assert client.get(f"/api/conversations/{conversation_id}", headers=bob).status_code == 404
        assert client.delete(f"/api/conversations/{conversation_id}", headers=bob).status_code == 404
        assert client.get(f"/api/conversations/{conversation_id}/messages", headers=bob).status_code == 404
        turned = client.post(
            f"/api/conversations/{conversation_id}/turns",
            json={"content": "hi"},
            headers=bob,
        )
    assert turned.status_code == 404


def test_cache_concurrent_gets_stay_within_the_cap(tmp_path: Path) -> None:
    from ai_agent.attachments.os_store import OSAttachmentStore
    from ai_agent.conversations.attachments import AttachmentCatalog
    from ai_agent.conversations.db import open_store_at
    from sqlalchemy.orm import Session

    from ai_agent.attachments.types import Attachment

    conversations = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    catalog = AttachmentCatalog(conversations.engine)
    blobs = OSAttachmentStore(tmp_path / "attachments", catalog, quota_count=10, quota_bytes=1000)
    conversation_id = conversations.create_conversation(ALICE).id
    ids = []
    for payload in (b"one", b"two"):
        attachment_id = blobs.put(ALICE, conversation_id, media_type="image/png", data=payload)
        ref = Attachment(
            id=attachment_id,
            user_id=ALICE,
            conversation_id=conversation_id,
            kind="image",
            media_type="image/png",
            byte_size=len(payload),
            checksum=checksum_bytes(payload),
        )
        with Session(conversations.engine) as db:
            catalog.insert(db, ref)
            db.commit()
        ids.append((attachment_id, ref.checksum))
    cache = AttachmentCache(blobs, max_bytes=4)
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def read(item: tuple[str, str]) -> None:
        start.wait()
        try:
            cache.get(ALICE, item[0], checksum=item[1])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=read, args=(item,)) for item in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert cache.size() <= 4


def test_pdf_upload_is_rejected(tmp_path: Path) -> None:
    client, _store, _holder = _api(tmp_path)
    headers = {"Authorization": "Bearer alice"}
    with client:
        conversation_id = client.post("/api/conversations", json={}, headers=headers).json()["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/turns",
            data={"content": "read this"},
            files=[("images", ("notes.pdf", b"%PDF-1.4", "application/pdf"))],
            headers=headers,
        )
    assert response.status_code == 400


def test_cache_does_not_store_a_checksum_mismatch(tmp_path: Path) -> None:
    from sqlalchemy.orm import Session

    from ai_agent.attachments.os_store import OSAttachmentStore
    from ai_agent.attachments.types import Attachment
    from ai_agent.conversations.attachments import AttachmentCatalog
    from ai_agent.conversations.db import open_store_at

    conversations = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    catalog = AttachmentCatalog(conversations.engine)
    blobs = OSAttachmentStore(tmp_path / "attachments", catalog)
    conversation_id = conversations.create_conversation(ALICE).id
    payload = b"png-bytes"
    attachment_id = blobs.put(ALICE, conversation_id, media_type="image/png", data=payload)
    with Session(conversations.engine) as db:
        catalog.insert(
            db,
            Attachment(
                id=attachment_id,
                user_id=ALICE,
                conversation_id=conversation_id,
                kind="image",
                media_type="image/png",
                byte_size=len(payload),
                checksum=checksum_bytes(payload),
            ),
        )
        db.commit()
    cache = AttachmentCache(blobs, max_bytes=1024)
    loaded = cache.get(ALICE, attachment_id, checksum="0" * 64)
    assert loaded == payload
    assert cache.size() == 0
