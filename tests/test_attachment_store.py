"""Filesystem attachment store: ownership, quotas, paths, reconcile."""

import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ai_agent.attachments.os_store import OSAttachmentStore
from ai_agent.attachments.runtime import reconcile_attachments
from ai_agent.attachments.store import AttachmentNotFound, AttachmentQuotaExceeded, AttachmentRejected
from ai_agent.attachments.types import Attachment, checksum_bytes
from ai_agent.conversations.attachments import AttachmentCatalog
from ai_agent.conversations.db import open_store_at

ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"


def _open(tmp_path: Path, *, quota_bytes: int = 1024, quota_count: int = 10):
    conversations = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    catalog = AttachmentCatalog(conversations.engine)
    root = tmp_path / "attachments"
    root.mkdir(mode=0o700)
    blobs = OSAttachmentStore(
        root,
        catalog,
        quota_bytes=quota_bytes,
        quota_count=quota_count,
    )
    return conversations, catalog, blobs


def _remember(conversations, catalog, user_id: str, conversation_id: str, attachment_id: str, data: bytes) -> Attachment:
    ref = Attachment(
        id=attachment_id,
        user_id=user_id,
        conversation_id=conversation_id,
        kind="image",
        media_type="image/png",
        byte_size=len(data),
        checksum=checksum_bytes(data),
    )
    with Session(conversations.engine) as db:
        catalog.insert(db, ref)
        db.commit()
    return ref


def test_put_get_stat_and_idempotent_delete(tmp_path: Path) -> None:
    conversations, catalog, blobs = _open(tmp_path)
    conversation_id = conversations.create_conversation(ALICE).id
    data = b"png-bytes"
    attachment_id = blobs.put(ALICE, conversation_id, media_type="image/png", data=data)
    ref = _remember(conversations, catalog, ALICE, conversation_id, attachment_id, data)
    assert blobs.get(ALICE, attachment_id) == data
    assert blobs.stat(ALICE, attachment_id) == ref
    stored = tmp_path / "attachments" / ALICE / conversation_id / attachment_id
    assert stored.stat().st_mode & 0o777 == 0o600
    assert stored.parent.stat().st_mode & 0o777 == 0o700
    blobs.delete(ALICE, attachment_id)
    blobs.delete(ALICE, attachment_id)
    assert not stored.exists()


def test_other_user_cannot_read_or_delete(tmp_path: Path) -> None:
    conversations, catalog, blobs = _open(tmp_path)
    conversation_id = conversations.create_conversation(ALICE).id
    data = b"secret"
    attachment_id = blobs.put(ALICE, conversation_id, media_type="image/png", data=data)
    _remember(conversations, catalog, ALICE, conversation_id, attachment_id, data)
    with pytest.raises(AttachmentNotFound):
        blobs.get(BOB, attachment_id)
    with pytest.raises(AttachmentNotFound):
        blobs.stat(BOB, attachment_id)
    with pytest.raises(AttachmentNotFound):
        blobs.delete(BOB, attachment_id)
    assert blobs.get(ALICE, attachment_id) == data


def test_path_traversal_and_symlink_are_rejected(tmp_path: Path) -> None:
    _conversations, _catalog, blobs = _open(tmp_path)
    victim = tmp_path / "victim"
    victim.mkdir()
    secret = victim / "secret"
    secret.write_bytes(b"keep")
    with pytest.raises((ValueError, AttachmentRejected)):
        blobs.put(ALICE, "../" + victim.name, media_type="image/png", data=b"nope")
    assert secret.read_bytes() == b"keep"

    user_dir = tmp_path / "attachments" / ALICE
    user_dir.mkdir(mode=0o700)
    conversation_id = "33333333-3333-4333-8333-333333333333"
    link = user_dir / conversation_id
    link.symlink_to(victim, target_is_directory=True)
    with pytest.raises(AttachmentRejected):
        blobs.put(ALICE, conversation_id, media_type="image/png", data=b"nope")
    assert secret.read_bytes() == b"keep"
    assert list(victim.iterdir()) == [secret]


def test_quota_is_per_user(tmp_path: Path) -> None:
    conversations, _catalog, blobs = _open(tmp_path, quota_bytes=10, quota_count=10)
    alice_chat = conversations.create_conversation(ALICE).id
    bob_chat = conversations.create_conversation(BOB).id
    blobs.put(ALICE, alice_chat, media_type="image/png", data=b"12345678")
    with pytest.raises(AttachmentQuotaExceeded):
        blobs.put(ALICE, alice_chat, media_type="image/png", data=b"12345678")
    blobs.put(BOB, bob_chat, media_type="image/png", data=b"12345678")


def test_quota_count_rejects_the_extra_object(tmp_path: Path) -> None:
    conversations, _catalog, blobs = _open(tmp_path, quota_bytes=10_000, quota_count=1)
    conversation_id = conversations.create_conversation(ALICE).id
    blobs.put(ALICE, conversation_id, media_type="image/png", data=b"a")
    with pytest.raises(AttachmentQuotaExceeded):
        blobs.put(ALICE, conversation_id, media_type="image/png", data=b"b")


def test_delete_conversation_is_idempotent_and_scoped(tmp_path: Path) -> None:
    conversations, catalog, blobs = _open(tmp_path)
    first = conversations.create_conversation(ALICE).id
    second = conversations.create_conversation(ALICE).id
    kept_id = blobs.put(ALICE, second, media_type="image/png", data=b"keep")
    _remember(conversations, catalog, ALICE, second, kept_id, b"keep")
    blobs.put(ALICE, first, media_type="image/png", data=b"gone")
    blobs.delete_conversation(ALICE, first)
    blobs.delete_conversation(ALICE, first)
    assert blobs.get(ALICE, kept_id) == b"keep"
    assert not (tmp_path / "attachments" / ALICE / first).exists()


def test_reconcile_removes_orphans_only(tmp_path: Path) -> None:
    conversations, catalog, blobs = _open(tmp_path)
    bob_chat = conversations.create_conversation(BOB).id
    kept_id = blobs.put(BOB, bob_chat, media_type="image/png", data=b"bob")
    _remember(conversations, catalog, BOB, bob_chat, kept_id, b"bob")
    orphan_id = str(uuid4())
    orphan = tmp_path / "attachments" / ALICE / str(uuid4()) / orphan_id
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    removed = reconcile_attachments(blobs, catalog)
    assert removed == 1
    assert not orphan.exists()
    assert blobs.get(BOB, kept_id) == b"bob"


def test_concurrent_puts_cannot_exceed_quota(tmp_path: Path) -> None:
    conversations, _catalog, blobs = _open(tmp_path, quota_count=1, quota_bytes=1000)
    conversation_id = conversations.create_conversation(ALICE).id
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def upload() -> None:
        start.wait()
        try:
            blobs.put(ALICE, conversation_id, media_type="image/png", data=b"x")
        except AttachmentQuotaExceeded as exc:
            errors.append(exc)

    threads = [threading.Thread(target=upload) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(errors) == 1
    files = [
        entry
        for entry in os.scandir(tmp_path / "attachments" / ALICE / conversation_id)
        if entry.is_file() and not entry.name.startswith(".")
    ]
    assert len(files) == 1


def test_sqlite_failure_after_put_removes_the_file(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from ai_agent.api.conversations import _commit_images
    from ai_agent.llm.client.types import ImageInput

    conversations, catalog, blobs = _open(tmp_path)
    conversation_id = conversations.create_conversation(ALICE).id

    def fail(*_args, **_kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(conversations, "append_message_in", fail)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                attachment_store=blobs,
                attachment_catalog=catalog,
                attachment_cache=None,
            )
        )
    )
    with pytest.raises(RuntimeError, match="sqlite down"):
        _commit_images(
            request,
            conversations,
            user_id=ALICE,
            conversation_id=conversation_id,
            content="look",
            images=[ImageInput(data=b"png", media_type="image/png")],
        )
    assert conversations.list_messages(ALICE, conversation_id) == []
    user_dir = tmp_path / "attachments" / ALICE / conversation_id
    leftovers = [path for path in user_dir.iterdir() if path.is_file() and not path.name.startswith(".")] if user_dir.exists() else []
    assert leftovers == []
