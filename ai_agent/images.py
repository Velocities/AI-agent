"""Validate uploaded images and parse CLI image attachments.

The bytes stay provider-neutral. Ollama and vLLM adapters translate
`ImageInput` into their own request bodies.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent.llm.client.types import ImageInput

DEFAULT_IMAGE_MAX_BYTES = 10 * 1024 * 1024

ALLOWED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

_IMAGE_TOKEN = re.compile(r"(?<!\S)@(\S+)")
_IMAGE_SUFFIX = re.compile(r"\.(?:png|jpe?g|webp)$", re.IGNORECASE)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImageRejected(ValueError):
    """An upload or CLI attachment cannot be sent to a model."""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_image_bytes(
    data: bytes,
    *,
    declared_type: str | None = None,
    max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
) -> ImageInput:
    """Accept PNG, JPEG, and WebP bytes. Reject everything else.

    The media type comes from the file contents. A filename is never enough,
    and a declared type is only accepted when it matches those contents.
    """
    if not data:
        raise ImageRejected("Invalid image data.")
    if len(data) > max_bytes:
        raise ImageRejected(
            f"Image is too large: {len(data)} bytes exceeds the limit of {max_bytes} bytes.",
            status_code=413,
        )

    declared = _normalize_media_type(declared_type)
    if declared is not None and declared not in ALLOWED_IMAGE_TYPES:
        raise ImageRejected(f"Unsupported image type: {declared}")

    sniffed = sniff_image_media_type(data)
    if sniffed is not None and sniffed not in ALLOWED_IMAGE_TYPES:
        raise ImageRejected(f"Unsupported image type: {sniffed}")
    if sniffed not in ALLOWED_IMAGE_TYPES:
        raise ImageRejected("Invalid image data.")
    if declared is not None and declared != sniffed:
        raise ImageRejected("Invalid image data.")
    if not _structure_ok(data, sniffed):
        raise ImageRejected("Invalid image data.")
    from ai_agent.llm.client.types import ImageInput

    return ImageInput(data=data, media_type=sniffed)


def sniff_image_media_type(data: bytes) -> str | None:
    """Return a media type when the leading bytes identify a known image."""
    if data.startswith(_PNG_SIGNATURE):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return None


def parse_image_prompt(
    text: str,
    *,
    max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
) -> tuple[str, list[ImageInput]]:
    """Split `@path.png` tokens out of a CLI line.

    Tokens that do not end in a supported image extension stay in the text.
    Image tokens are removed and loaded in left-to-right order.
    """
    images: list[ImageInput] = []
    pieces: list[str] = []
    cursor = 0
    for match in _IMAGE_TOKEN.finditer(text):
        token = match.group(1)
        if _IMAGE_SUFFIX.search(token) is None:
            continue
        pieces.append(text[cursor : match.start()])
        images.append(_load_image_file(token, max_bytes=max_bytes))
        cursor = match.end()
    if not images:
        return text, []
    pieces.append(text[cursor:])
    content = re.sub(r"[ \t]{2,}", " ", "".join(pieces)).strip()
    return content, images


def _load_image_file(token: str, *, max_bytes: int) -> ImageInput:
    path = Path(token).expanduser()
    if not path.is_file():
        raise ImageRejected(f"Image file not found: {token}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ImageRejected(f"Could not read image file: {token}") from exc
    return validate_image_bytes(data, max_bytes=max_bytes)


def _normalize_media_type(value: str | None) -> str | None:
    if not value:
        return None
    media = value.split(";", 1)[0].strip().lower()
    if media in {"", "application/octet-stream", "binary/octet-stream"}:
        return None
    if media in {"image/jpg", "image/pjpeg"}:
        return "image/jpeg"
    if media == "image/x-png":
        return "image/png"
    return media


def _structure_ok(data: bytes, media_type: str) -> bool:
    if media_type == "image/png":
        return _png_ok(data)
    if media_type == "image/jpeg":
        return _jpeg_ok(data)
    if media_type == "image/webp":
        return _webp_ok(data)
    return False


def _png_ok(data: bytes) -> bool:
    if not data.startswith(_PNG_SIGNATURE):
        return False
    index = len(_PNG_SIGNATURE)
    seen_ihdr = False
    while index + 8 <= len(data):
        length = int.from_bytes(data[index : index + 4], "big")
        chunk_type = data[index + 4 : index + 8]
        index += 8
        if index + length + 4 > len(data):
            return False
        if not seen_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                return False
            seen_ihdr = True
        index += length + 4
        if chunk_type == b"IEND":
            return True
    return False


def _jpeg_ok(data: bytes) -> bool:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        return False
    index = 2
    seen_segment = False
    while index < len(data):
        if data[index] != 0xFF:
            return False
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            return False
        marker = data[index]
        index += 1
        if marker == 0xD9:
            return seen_segment
        if marker in {0x00, 0xD8}:
            return False
        seen_segment = True
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            return False
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            return False
        if marker == 0xDA:
            scan = index + length
            while scan + 1 < len(data):
                if data[scan] == 0xFF and data[scan + 1] == 0xD9:
                    return True
                scan += 1
            return False
        index += length
    return False


def _webp_ok(data: bytes) -> bool:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    fourcc = data[12:16]
    if fourcc not in {b"VP8 ", b"VP8L", b"VP8X"}:
        return False
    chunk_size = int.from_bytes(data[16:20], "little")
    if chunk_size < 1:
        return False
    return 20 + chunk_size <= len(data)
