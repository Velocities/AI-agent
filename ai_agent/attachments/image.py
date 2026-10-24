"""The only attachment handler this deployment ships: PNG, JPEG, and WebP."""

from __future__ import annotations

from ai_agent.attachments.types import Attachment, ValidatedUpload
from ai_agent.config import Settings
from ai_agent.conversations.user_settings import UserSettingsStore
from ai_agent.images import (
    ALLOWED_IMAGE_TYPES,
    normalize_media_type,
    sniff_image_media_type,
    strip_image_metadata,
    validate_image_bytes,
)
from ai_agent.llm.client.types import ImageInput


class ImageHandler:
    kind = "image"

    def match(self, data: bytes, declared_type: str | None) -> bool:
        sniffed = sniff_image_media_type(data)
        if sniffed not in ALLOWED_IMAGE_TYPES:
            return False
        declared = normalize_media_type(declared_type)
        if declared is not None and declared not in ALLOWED_IMAGE_TYPES:
            return False
        return True

    def validate(
        self,
        data: bytes,
        *,
        settings: Settings,
        declared_type: str | None = None,
    ) -> ValidatedUpload:
        image = validate_image_bytes(
            data,
            declared_type=declared_type,
            max_bytes=settings.image_max_bytes,
            max_pixels=settings.image_max_pixels,
            max_dimension=settings.image_max_dimension,
        )
        return ValidatedUpload(data=image.data, media_type=image.media_type, kind=self.kind)

    def prepare(
        self,
        upload: ValidatedUpload,
        *,
        user_settings: UserSettingsStore | None,
        user_id: str,
    ) -> ValidatedUpload:
        strip = True
        if user_settings is not None:
            strip = user_settings.get_strip_image_metadata(user_id)
        if not strip:
            return upload
        cleaned = strip_image_metadata(
            ImageInput(data=upload.data, media_type=upload.media_type)
        )
        return ValidatedUpload(data=cleaned.data, media_type=cleaned.media_type, kind=self.kind)

    def to_model(self, attachment: Attachment, data: bytes) -> ImageInput | None:
        if attachment.kind != self.kind:
            return None
        return ImageInput(
            data=data,
            media_type=attachment.media_type,
            attachment_id=attachment.id,
        )
