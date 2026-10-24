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
SECRET = b"gps-secret-marker"


def jpeg_with_location() -> bytes:
    from PIL.ExifTags import IFD
    from PIL.TiffImagePlugin import IFDRational

    original = Image.new("RGB", (4, 2), (0, 0, 0))
    original.putpixel((0, 0), (255, 0, 0))
    original.putpixel((3, 1), (0, 0, 255))
    exif = original.getexif()
    exif[270] = SECRET.decode("ascii")
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

    image = Image.new("RGB", (1, 1), (9, 9, 9))
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", SECRET.decode("ascii"))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def webp_with_exif() -> bytes:
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
    return client.post(
        f"/api/conversations/{conversation_id}/turns",
        data={"content": "Where was this taken?"},
        files=[("images", (filename, data, media_type))],
        headers=HEADERS,
    )


def _stored_and_sent(client, holder):
    image = holder["agent"].images[0]
    stored = client.app.state.attachment_store.get(ALICE, image.attachment_id)
    return image, stored


def _transcript(store, conversation_id: str) -> str:
    rows = store.list_messages(ALICE, conversation_id)
    return json.dumps([row.metadata for row in rows])


def _assert_stripped(data: bytes, media_type: str) -> None:
    assert SECRET not in data
    checked = validate_image_bytes(data, declared_type=media_type)
    assert checked.data == data
    assert checked.media_type == media_type
    if media_type != "image/jpeg":
        return
    from PIL.ExifTags import IFD

    opened = Image.open(io.BytesIO(data))
    assert not opened.getexif().get_ifd(IFD.GPSInfo)
    assert opened.size == (2, 4)


def _assert_retained(data: bytes, raw: bytes, media_type: str) -> None:
    assert data == raw
    assert SECRET in data
    if media_type != "image/jpeg":
        return
    from PIL.ExifTags import IFD

    opened = Image.open(io.BytesIO(data))
    assert opened.getexif().get_ifd(IFD.GPSInfo)
    assert opened.size == (4, 2)


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
    assert SECRET in raw
    client, store, holder = _api(tmp_path)
    with client:
        settings = client.get("/api/me/settings", headers=HEADERS)
        conversation_id = _conversation(client)
        response = _upload(client, conversation_id, filename, raw, media_type)
        image, stored = _stored_and_sent(client, holder)
        transcript = _transcript(store, conversation_id)
    assert settings.status_code == 200
    assert settings.json() == {"strip_image_metadata": True}
    assert response.status_code == 200
    assert stored == image.data
    assert stored != raw
    assert image.media_type == media_type
    assert image.attachment_id
    _assert_stripped(stored, media_type)
    _assert_stripped(image.data, media_type)
    assert SECRET not in transcript.encode()
    user = store.list_messages(ALICE, conversation_id)[0]
    attachment = user.metadata["attachments"][0]
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
    assert SECRET not in transcript.encode()


def test_failed_strip_does_not_store_the_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = jpeg_with_location()
    assert SECRET in raw
    client, store, holder = _api(tmp_path)

    def boom(self, *args, **kwargs):
        raise OSError("cannot save")

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
    assert "agent" not in holder
    assert SECRET not in response.content
