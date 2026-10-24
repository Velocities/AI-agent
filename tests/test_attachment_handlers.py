"""ImageHandler is the only upload handler."""

import ai_agent.attachments as attachments
from ai_agent.attachments import HANDLERS, select_handler
from ai_agent.attachments.image import ImageHandler
from ai_agent.attachments.types import Attachment, ValidatedUpload
from ai_agent.config import Settings
from ai_agent.images import strip_image_metadata, validate_image_bytes
from tests.test_images import jpeg_bytes, png_bytes


class _Settings:
    def get_strip_image_metadata(self, _user_id: str) -> bool:
        return self.value

    def __init__(self, value: bool) -> None:
        self.value = value


def test_only_the_image_handler_is_registered() -> None:
    assert len(HANDLERS) == 1
    assert isinstance(HANDLERS[0], ImageHandler)
    assert not hasattr(attachments, "PdfHandler")
    assert not hasattr(attachments, "DocumentHandler")
    assert not hasattr(attachments, "OSAttachmentStore")
    assert select_handler(b"%PDF-1.4", "application/pdf") is None
    assert isinstance(select_handler(png_bytes(), "image/png"), ImageHandler)


def test_image_handler_prepares_and_builds_model_input() -> None:
    handler = ImageHandler()
    raw = jpeg_bytes()
    upload = handler.validate(raw, settings=Settings(), declared_type="image/jpeg")
    stripped = handler.prepare(
        upload,
        user_settings=_Settings(True),
        user_id="11111111-1111-4111-8111-111111111111",
    )
    assert stripped.kind == "image"
    assert stripped.data == strip_image_metadata(validate_image_bytes(raw)).data
    original = handler.prepare(
        upload,
        user_settings=_Settings(False),
        user_id="11111111-1111-4111-8111-111111111111",
    )
    assert original.data == raw
    attachment = Attachment(
        id="44444444-4444-4444-8444-444444444444",
        user_id="11111111-1111-4111-8111-111111111111",
        conversation_id="55555555-5555-4555-8555-555555555555",
        kind="image",
        media_type="image/jpeg",
        byte_size=len(stripped.data),
        checksum="abc",
    )
    model = handler.to_model(attachment, stripped.data)
    assert model is not None
    assert model.attachment_id == attachment.id
    assert model.media_type == "image/jpeg"
    assert not hasattr(handler, "save")
    assert not hasattr(handler, "put")


def test_load_bytes_calls_get_on_the_store() -> None:
    seen: dict[str, str] = {}

    class _Store:
        def get(self, user_id: str, attachment_id: str) -> bytes:
            seen["user_id"] = user_id
            seen["attachment_id"] = attachment_id
            return b"payload"

    attachment = Attachment(
        id="44444444-4444-4444-8444-444444444444",
        user_id="11111111-1111-4111-8111-111111111111",
        conversation_id="55555555-5555-4555-8555-555555555555",
        kind="image",
        media_type="image/png",
        byte_size=7,
        checksum="abc",
    )
    assert attachment.load_bytes(_Store()) == b"payload"
    assert seen == {
        "user_id": attachment.user_id,
        "attachment_id": attachment.id,
    }
    assert isinstance(ValidatedUpload(data=b"x", media_type="image/png", kind="image"), ValidatedUpload)
