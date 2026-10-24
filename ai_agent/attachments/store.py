"""Attachment storage protocol and errors.

Callers depend on `AttachmentStore`. The on-disk implementation stays in
`os_store` so a later object store can replace it without touching the agent.
"""

from __future__ import annotations

from typing import Protocol

from ai_agent.attachments.types import Attachment

DEFAULT_ATTACHMENT_QUOTA_BYTES = 512 * 1024 * 1024
DEFAULT_ATTACHMENT_QUOTA_COUNT = 200
DEFAULT_ATTACHMENT_CACHE_BYTES = 64 * 1024 * 1024
DEFAULT_ATTACHMENT_REPLAY_MESSAGES = 4
DEFAULT_ATTACHMENT_REPLAY_MAX_IMAGES = 8
DEFAULT_ATTACHMENT_REPLAY_MAX_BYTES = 16 * 1024 * 1024


class AttachmentError(Exception):
    """Storage rejected or could not find an attachment."""


class AttachmentNotFound(LookupError, AttachmentError):
    """No attachment with this id belongs to this user."""


class AttachmentQuotaExceeded(AttachmentError):
    status_code = 413

    def __init__(self, message: str = "Attachment storage quota exceeded."):
        super().__init__(message)


class AttachmentRejected(AttachmentError):
    status_code = 400


class AttachmentStore(Protocol):
    """Opaque storage for conversation attachment bytes."""

    def put(
        self,
        user_id: str,
        conversation_id: str,
        *,
        media_type: str,
        data: bytes,
    ) -> str:
        """Persist bytes and return an opaque attachment id."""

    def get(self, user_id: str, attachment_id: str) -> bytes:
        """Return raw bytes. Raise AttachmentNotFound when missing or not this user's."""

    def stat(self, user_id: str, attachment_id: str) -> Attachment:
        """kind, media_type, byte_size, checksum. No payload."""

    def delete(self, user_id: str, attachment_id: str) -> None:
        """Idempotent. Missing object is success. Never delete another user's data."""

    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        """Idempotent. Remove every object for this chat only."""
