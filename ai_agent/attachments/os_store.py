"""Local-disk attachment bytes. The catalog is the source of truth for paths."""

from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path

from ai_agent.attachments.ids import ID_RE, new_attachment_id, validate_id
from ai_agent.attachments.store import (
    DEFAULT_ATTACHMENT_QUOTA_BYTES,
    DEFAULT_ATTACHMENT_QUOTA_COUNT,
    AttachmentNotFound,
    AttachmentQuotaExceeded,
    AttachmentRejected,
)
from ai_agent.attachments.types import Attachment
from ai_agent.conversations.attachments import AttachmentCatalog

logger = logging.getLogger(__name__)

_PENDING = tuple[str, int]  # conversation_id, size


class OSAttachmentStore:
    """Store raw bytes at `{root}/{user_id}/{conversation_id}/{attachment_id}`."""

    def __init__(
        self,
        root: Path,
        catalog: AttachmentCatalog,
        *,
        quota_bytes: int = DEFAULT_ATTACHMENT_QUOTA_BYTES,
        quota_count: int = DEFAULT_ATTACHMENT_QUOTA_COUNT,
    ):
        self.root = root.resolve()
        self._catalog = catalog
        self.quota_bytes = quota_bytes
        self.quota_count = quota_count
        self._registry_lock = threading.Lock()
        self._user_locks: dict[str, threading.Lock] = {}
        self._pending: dict[str, dict[str, _PENDING]] = {}

    def put(
        self,
        user_id: str,
        conversation_id: str,
        *,
        media_type: str,
        data: bytes,
    ) -> str:
        user = validate_id(user_id, what="user id")
        conversation = validate_id(conversation_id, what="conversation id")
        attachment_id = new_attachment_id()
        with self._lock_for(user):
            self._release_committed_pending(user)
            used_bytes, used_count = self._catalog.totals_for_user(user)
            pending = self._pending.get(user, {})
            pending_bytes = sum(size for _conversation, size in pending.values())
            if used_bytes + pending_bytes + len(data) > self.quota_bytes:
                raise AttachmentQuotaExceeded()
            if used_count + len(pending) + 1 > self.quota_count:
                raise AttachmentQuotaExceeded()
            self._write_file(user, conversation, attachment_id, data)
            self._pending.setdefault(user, {})[attachment_id] = (conversation, len(data))
        return attachment_id

    def get(self, user_id: str, attachment_id: str) -> bytes:
        row = self._owned_row(user_id, attachment_id)
        path = self._file_path(row.user_id, row.conversation_id, row.id)
        self._refuse_symlink(path)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise AttachmentNotFound(attachment_id) from exc
        except OSError as exc:
            raise AttachmentNotFound(attachment_id) from exc

    def stat(self, user_id: str, attachment_id: str) -> Attachment:
        return self._owned_row(user_id, attachment_id)

    def delete(self, user_id: str, attachment_id: str) -> None:
        user = validate_id(user_id, what="user id")
        attachment = validate_id(attachment_id, what="attachment id")
        row = self._catalog.get(user, attachment)
        if row is None:
            owner = self._catalog.owner_of(attachment)
            if owner is not None and owner != user:
                raise AttachmentNotFound(attachment)
            self._unlink_orphan(user, attachment)
            self._drop_pending(user, attachment)
            return
        path = self._file_path(row.user_id, row.conversation_id, row.id)
        self._unlink_file(path)
        self._drop_pending(user, attachment)

    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        user = validate_id(user_id, what="user id")
        conversation = validate_id(conversation_id, what="conversation id")
        directory = self.root / user / conversation
        if directory.is_symlink():
            raise AttachmentRejected("Refusing to follow a symlink.")
        if not directory.exists():
            self._drop_pending_conversation(user, conversation)
            return
        resolved = directory.resolve(strict=True)
        prefix = (self.root / user).resolve(strict=False)
        expected = (self.root / user / conversation).resolve(strict=False)
        if resolved != expected or not _is_under(resolved, prefix):
            raise AttachmentRejected("Attachment path escapes the conversation directory.")
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                if not ID_RE.match(entry.name):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    os.unlink(entry.path)
                except FileNotFoundError:
                    continue
        try:
            directory.rmdir()
        except OSError:
            logger.debug("Conversation attachment directory was not empty: %s", directory)
        self._drop_pending_conversation(user, conversation)

    def _owned_row(self, user_id: str, attachment_id: str) -> Attachment:
        user = validate_id(user_id, what="user id")
        attachment = validate_id(attachment_id, what="attachment id")
        row = self._catalog.get(user, attachment)
        if row is None:
            raise AttachmentNotFound(attachment)
        return row

    def _write_file(self, user: str, conversation: str, attachment_id: str, data: bytes) -> None:
        directory = self.root / user / conversation
        path = directory / attachment_id
        self._assert_contained(path, user)
        if path.is_symlink() or directory.is_symlink() or (self.root / user).is_symlink():
            raise AttachmentRejected("Refusing to follow a symlink.")
        self._mkdir_private(self.root / user)
        self._mkdir_private(directory)
        if directory.is_symlink() or path.is_symlink():
            raise AttachmentRejected("Refusing to follow a symlink.")
        self._assert_contained(path, user)
        temp_name = f".{attachment_id}.{secrets.token_hex(6)}.partial"
        temp_path = directory / temp_name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        elif temp_path.is_symlink():
            raise AttachmentRejected("Refusing to follow a symlink.")
        fd = os.open(temp_path, flags, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        except Exception:
            os.close(fd)
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
        os.close(fd)
        try:
            os.replace(temp_path, path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
        os.chmod(path, 0o600)

    def _mkdir_private(self, directory: Path) -> None:
        if directory.is_symlink():
            raise AttachmentRejected("Refusing to follow a symlink.")
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise AttachmentRejected("Refusing to follow a symlink.")
        directory.chmod(0o700)

    def _assert_contained(self, path: Path, user: str) -> None:
        resolved = path.resolve(strict=False)
        prefix = (self.root / user).resolve(strict=False)
        root = self.root.resolve(strict=False)
        if not _is_under(resolved, root) or not _is_under(resolved, prefix):
            raise AttachmentRejected("Attachment path escapes the user directory.")

    def _file_path(self, user: str, conversation: str, attachment_id: str) -> Path:
        path = self.root / user / conversation / attachment_id
        self._assert_contained(path, user)
        return path

    def _refuse_symlink(self, path: Path) -> None:
        user_dir = path.parent.parent
        conversation_dir = path.parent
        if path.is_symlink() or conversation_dir.is_symlink() or user_dir.is_symlink():
            raise AttachmentRejected("Refusing to follow a symlink.")

    def _unlink_file(self, path: Path) -> None:
        if path.is_symlink():
            raise AttachmentRejected("Refusing to follow a symlink.")
        try:
            path.unlink(missing_ok=True)
        except FileNotFoundError:
            return

    def _unlink_orphan(self, user: str, attachment_id: str) -> None:
        user_dir = self.root / user
        if not user_dir.is_dir() or user_dir.is_symlink():
            return
        with os.scandir(user_dir) as conversations:
            for conversation in conversations:
                if conversation.is_symlink() or not conversation.is_dir(follow_symlinks=False):
                    continue
                if not ID_RE.match(conversation.name):
                    continue
                candidate = Path(conversation.path) / attachment_id
                if candidate.is_symlink():
                    continue
                if candidate.is_file():
                    self._unlink_file(candidate)
                    return

    def _lock_for(self, user_id: str) -> threading.Lock:
        with self._registry_lock:
            lock = self._user_locks.get(user_id)
            if lock is None:
                lock = threading.Lock()
                self._user_locks[user_id] = lock
            return lock

    def _release_committed_pending(self, user: str) -> None:
        pending = self._pending.get(user)
        if not pending:
            return
        for attachment_id in list(pending):
            if self._catalog.get(user, attachment_id) is not None:
                pending.pop(attachment_id, None)
        if not pending:
            self._pending.pop(user, None)

    def _drop_pending(self, user: str, attachment_id: str) -> None:
        pending = self._pending.get(user)
        if not pending:
            return
        pending.pop(attachment_id, None)
        if not pending:
            self._pending.pop(user, None)

    def _drop_pending_conversation(self, user: str, conversation: str) -> None:
        pending = self._pending.get(user)
        if not pending:
            return
        for attachment_id, (conversation_id, _size) in list(pending.items()):
            if conversation_id == conversation:
                pending.pop(attachment_id, None)
        if not pending:
            self._pending.pop(user, None)


def _is_under(path: Path, prefix: Path) -> bool:
    return path == prefix or str(path).startswith(str(prefix) + os.sep)
