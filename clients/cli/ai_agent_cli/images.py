"""Client-side image checks before upload. The server enforces again on receive."""

from __future__ import annotations

import io
import threading
import warnings
from dataclasses import dataclass

from PIL import Image, ImageFile, UnidentifiedImageError
from PIL.Image import DecompressionBombError, DecompressionBombWarning

from ai_agent_cli.types import ImageInput

DEFAULT_IMAGE_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_IMAGE_MAX_COUNT = 8
DEFAULT_IMAGE_MAX_PIXELS = 20_000_000
DEFAULT_IMAGE_MAX_DIMENSION = 8192
DEFAULT_ATTACHMENT_REPLAY_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_ATTACHMENT_REPLAY_MAX_IMAGES = 8

ALLOWED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PILLOW_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
_PILLOW_LOCK = threading.RLock()
ImageFile.LOAD_TRUNCATED_IMAGES = False


class ImageRejected(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_image_bytes(
    data: bytes,
    *,
    max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
    max_pixels: int = DEFAULT_IMAGE_MAX_PIXELS,
    max_dimension: int = DEFAULT_IMAGE_MAX_DIMENSION,
) -> ImageInput:
    if not data:
        raise ImageRejected("Invalid image data.")
    if len(data) > max_bytes:
        raise ImageRejected(
            f"Image is too large: {len(data)} bytes exceeds the limit of {max_bytes} bytes.",
            status_code=413,
        )
    sniffed = _sniff_image_media_type(data)
    if sniffed not in ALLOWED_IMAGE_TYPES:
        raise ImageRejected("Invalid image data.")
    _decode_image(
        data, sniffed=sniffed, max_pixels=max_pixels, max_dimension=max_dimension
    )
    return ImageInput(data=data, media_type=sniffed)


def maybe_strip_for_transit(image: ImageInput) -> ImageInput:
    return image


def _sniff_image_media_type(data: bytes) -> str | None:
    if data.startswith(_PNG_SIGNATURE):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _decode_image(
    data: bytes,
    *,
    sniffed: str,
    max_pixels: int,
    max_dimension: int,
) -> None:
    with _PILLOW_LOCK:
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = max_pixels
        probe = None
        image = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", DecompressionBombWarning)
                try:
                    probe = Image.open(io.BytesIO(data))
                    probe.verify()
                except ImageRejected:
                    raise
                except (
                    UnidentifiedImageError,
                    DecompressionBombError,
                    DecompressionBombWarning,
                    OSError,
                    SyntaxError,
                    ValueError,
                ) as exc:
                    _reject_decode(exc)
                finally:
                    if probe is not None:
                        probe.close()
                try:
                    image = Image.open(io.BytesIO(data))
                    image.load()
                except (
                    UnidentifiedImageError,
                    DecompressionBombError,
                    DecompressionBombWarning,
                    OSError,
                    SyntaxError,
                    ValueError,
                ) as exc:
                    _reject_decode(exc)
                frames = getattr(image, "n_frames", 1) or 1
                if frames > 1:
                    raise ImageRejected("Invalid image data.")
                reported = _PILLOW_FORMATS.get(image.format or "")
                if reported != sniffed:
                    raise ImageRejected("Invalid image data.")
                width, height = image.size
                if width < 1 or height < 1:
                    raise ImageRejected("Invalid image data.")
                if (
                    width > max_dimension
                    or height > max_dimension
                    or width * height > max_pixels
                ):
                    raise ImageRejected(
                        f"Image dimensions {width}x{height} exceed the limit.",
                        status_code=413,
                    )
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit
            if image is not None:
                image.close()


def _reject_decode(exc: BaseException) -> None:
    status = (
        413 if isinstance(exc, (DecompressionBombError, DecompressionBombWarning)) else 400
    )
    raise ImageRejected("Invalid image data.", status_code=status) from exc