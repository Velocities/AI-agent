"""POST /turns strips image metadata before the file is stored or sent to the model.

The preference lives on GET/PATCH /api/me/settings. A missing row strips.
"""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from ai_agent.images import validate_image_bytes
from tests.test_images import ALICE, _api

HEADERS = {"Authorization": "Bearer alice"}
# Shared marker so each format can be checked by searching the stored bytes.
SECRET = b"gps-secret-marker"


def jpeg_with_location() -> bytes:
    from PIL.ExifTags import IFD
    from PIL.TiffImagePlugin import IFDRational

    # 4x2 with Orientation=6 (rotate 90°). A successful strip stores 2x4 pixels.
    original = Image.new("RGB", (4, 2), (0, 0, 0))
    original.putpixel((0, 0), (255, 0, 0))
    original.putpixel((3, 1), (0, 0, 255))
    exif = original.getexif()
    exif[270] = SECRET.decode("ascii")  # ImageDescription, the searchable marker.
    exif[274] = 6
    gps = exif.get_ifd(IFD.GPSInfo)
    gps[1] = "N"
    gps[2] = (IFDRational(37, 1), IFDRational(48, 1), IFDRational(0, 1))
    gps[3] = "W"
    gps[4] = (IFDRational(122, 1), IFDRational(25, 1), IFDRational(0, 1))
    buffer = io.BytesIO()
    original.save(buffer, format="JPEG", quality=95, exif=exif)
    return buffer.getvalue()


def png_with_text() -> bytes:
    from PIL import PngImagePlugin

    # tEXt comment. Strip must drop pnginfo; the opt-out path must keep this string.
    image = Image.new("RGB", (1, 1), (9, 9, 9))
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", SECRET.decode("ascii"))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def webp_with_exif() -> bytes:
    # EXIF description. Orientation 1 means the pixels should not be rotated.
    image = Image.new("RGB", (2, 2), (1, 2, 3))
    exif = image.getexif()
    exif[270] = SECRET.decode("ascii")
    exif[274] = 1
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=95, exif=exif)
    return buffer.getvalue()


def _conversation(client) -> str:
    created = client.post("/api/conversations", json={}, headers=HEADERS)
    assert created.status_code == 200
    return created.json()["id"]


def _upload(client, conversation_id: str, filename: str, data: bytes, media_type: str):
    # Multipart turn: the same route a client uses to attach an image.
    return client.post(
        f"/api/conversations/{conversation_id}/turns",
        data={"content": "Where was this taken?"},
        files=[("images", (filename, data, media_type))],
        headers=HEADERS,
    )


def _stored_and_sent(client, holder):
    # Model payload and the blob written for that attachment id.
    image = holder["agent"].images[0]
    stored = client.app.state.attachment_store.get(ALICE, image.attachment_id)
    return image, stored


def _transcript(store, conversation_id: str) -> str:
    # Message metadata is what a later GET /messages would persist.
    rows = store.list_messages(ALICE, conversation_id)
    return json.dumps([row.metadata for row in rows])


def _assert_stripped(data: bytes, media_type: str) -> None:
    assert SECRET not in data
    # Re-encode must still be a valid image of the same type.
    checked = validate_image_bytes(data, declared_type=media_type)
    assert checked.data == data
    assert checked.media_type == media_type
    if media_type != "image/jpeg":
        return
    from PIL.ExifTags import IFD

    opened = Image.open(io.BytesIO(data))
    assert not opened.getexif().get_ifd(IFD.GPSInfo)
    assert opened.size == (2, 4)  # Orientation baked in; tag no longer required.


def _assert_retained(data: bytes, raw: bytes, media_type: str) -> None:
    # Opt-out stores the validated upload unchanged.
    assert data == raw
    assert SECRET in data
    if media_type != "image/jpeg":
        return
    from PIL.ExifTags import IFD

    opened = Image.open(io.BytesIO(data))
    assert opened.getexif().get_ifd(IFD.GPSInfo)
    assert opened.size == (4, 2)  # Pixels were not rotated.


@pytest.mark.parametrize(
    ("filename", "media_type", "build"),
    [
        ("photo.jpg", "image/jpeg", jpeg_with_location),
        ("note.png", "image/png", png_with_text),
        ("note.webp", "image/webp", webp_with_exif),
    ],
)
def test_turn_strips_metadata_before_store_and_model(tmp_path: Path, filename, media_type, build) -> None:
    raw = build()
    assert SECRET in raw  # Fixture actually contains the marker.
    client, store, holder = _api(tmp_path)
    with client:
        # No settings row yet. The default is to strip.
        settings = client.get("/api/me/settings", headers=HEADERS)
        conversation_id = _conversation(client)
        response = _upload(client, conversation_id, filename, raw, media_type)
        image, stored = _stored_and_sent(client, holder)
        transcript = _transcript(store, conversation_id)
    assert settings.status_code == 200
    assert settings.json() == {"strip_image_metadata": True}
    assert response.status_code == 200
    # Disk and the model see the same stripped bytes, not the upload.
    assert stored == image.data
    assert stored != raw
    assert image.media_type == media_type
    assert image.attachment_id
    _assert_stripped(stored, media_type)
    _assert_stripped(image.data, media_type)
    assert SECRET not in transcript.encode()
    user = store.list_messages(ALICE, conversation_id)[0]
    attachment = user.metadata["attachments"][0]
    # Transcript keeps an id and the stripped size, not the pixels.
    assert attachment["id"] == image.attachment_id
    assert attachment["media_type"] == media_type
    assert attachment["byte_size"] == len(stored)


@pytest.mark.parametrize(
    ("filename", "media_type", "build"),
    [
        ("photo.jpg", "image/jpeg", jpeg_with_location),
        ("note.png", "image/png", png_with_text),
        ("note.webp", "image/webp", webp_with_exif),
    ],
)
def test_turn_keeps_metadata_when_stripping_is_off(tmp_path: Path, filename, media_type, build) -> None:
    raw = build()
    assert SECRET in raw
    client, store, holder = _api(tmp_path)
    with client:
        # The settings route is what the turn handler reads back.
        updated = client.patch(
            "/api/me/settings",
            headers=HEADERS,
            json={"strip_image_metadata": False},
        )
        conversation_id = _conversation(client)
        response = _upload(client, conversation_id, filename, raw, media_type)
        image, stored = _stored_and_sent(client, holder)
        transcript = _transcript(store, conversation_id)
    assert updated.status_code == 200
    assert updated.json() == {"strip_image_metadata": False}
    assert response.status_code == 200
    assert stored == image.data
    _assert_retained(stored, raw, media_type)
    _assert_retained(image.data, raw, media_type)
    # Opting out keeps the tag on disk. It still must not land in the transcript.
    assert SECRET not in transcript.encode()


def test_failed_strip_does_not_store_the_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = jpeg_with_location()
    assert SECRET in raw
    client, store, holder = _api(tmp_path)

    def boom(self, *args, **kwargs):
        raise OSError("cannot save")

    # Strip re-saves the image. A failure here must not fall back to the original.
    monkeypatch.setattr(Image.Image, "save", boom)
    with client:
        conversation_id = _conversation(client)
        response = _upload(client, conversation_id, "photo.jpg", raw, "image/jpeg")
        root = client.app.state.attachment_store.root
        files = [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
        messages = store.list_messages(ALICE, conversation_id)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid image data."
    assert files == []
    assert messages == []
    assert "agent" not in holder  # The model never received the upload.
    assert SECRET not in response.content
