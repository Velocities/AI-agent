"""How one attachment kind is checked and turned into model input.

The process registry contains only `ImageHandler`. A later document type is
a new module plus one more entry in `HANDLERS`. There is no plugin loader
and no per-type `save`.
"""

from __future__ import annotations

from typing import Protocol

from ai_agent.attachments.image import ImageHandler
from ai_agent.attachments.types import Attachment, ValidatedUpload
from ai_agent.config import Settings
from ai_agent.conversations.user_settings import UserSettingsStore
from ai_agent.llm.client.types import ImageInput

HANDLERS: tuple[ImageHandler, ...] = (ImageHandler(),)


class AttachmentHandler(Protocol):
    kind: str

    def match(self, data: bytes, declared_type: str | None) -> bool: ...

    def validate(
        self,
        data: bytes,
        *,
        settings: Settings,
        declared_type: str | None = None,
    ) -> ValidatedUpload: ...

    def prepare(
        self,
        upload: ValidatedUpload,
        *,
        user_settings: UserSettingsStore | None,
        user_id: str,
    ) -> ValidatedUpload: ...

    def to_model(self, attachment: Attachment, data: bytes) -> ImageInput | None: ...


def select_handler(data: bytes, declared_type: str | None) -> AttachmentHandler | None:
    """First matching handler wins. None means this upload is not accepted."""
    for handler in HANDLERS:
        if handler.match(data, declared_type):
            return handler
    return None
