"""Saved-file record and the in-memory result of validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent.attachments.store import AttachmentStore


@dataclass(frozen=True)
class Attachment:
    """One file the server has accepted and catalogued.

    `load_bytes` fetches the payload from whatever object implements `get`.
    It does not know about caches, quotas, or image codecs.
    """

    id: str
    user_id: str
    conversation_id: str
    kind: str
    media_type: str
    byte_size: int
    checksum: str

    def load_bytes(self, blobs: AttachmentStore) -> bytes:
        return blobs.get(self.user_id, self.id)


@dataclass(frozen=True)
class ValidatedUpload:
    """Bytes that passed a handler's validate/prepare steps and are not stored yet."""

    data: bytes
    media_type: str
    kind: str


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
