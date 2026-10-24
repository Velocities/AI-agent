"""Validate uploaded images and strip metadata at the agent boundary.

The bytes stay provider-neutral. Ollama and vLLM adapters translate
`ImageInput` into their own request bodies. Decode and metadata removal
use Pillow. Clients may sniff and check size for UX; this module is the
security boundary.
"""

from __future__ import annotations

import io
import logging
import threading
import warnings
from typing import TYPE_CHECKING

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError, DecompressionBombWarning

if TYPE_CHECKING:
    from ai_agent.llm.client.types import ImageInput

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_IMAGE_MAX_COUNT = 8
DEFAULT_IMAGE_MAX_PIXELS = 20_000_000
DEFAULT_IMAGE_MAX_DIMENSION = 8192

ALLOWED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PILLOW_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
_PILLOW_LOCK = threading.RLock()

# Truncated files are rejected. Never enable Pillow's truncated-image loader.
ImageFile.LOAD_TRUNCATED_IMAGES = False


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
    max_pixels: int = DEFAULT_IMAGE_MAX_PIXELS,
    max_dimension: int = DEFAULT_IMAGE_MAX_DIMENSION,
) -> ImageInput:
    """Accept PNG, JPEG, and WebP bytes. Reject everything else.

    The media type comes from the file contents. A filename is never enough,
    and a declared type is only accepted when it matches those contents.
    Returns the original bytes. Metadata stripping is a separate step.
    """
    if not data:
        raise ImageRejected("Invalid image data.")
    if len(data) > max_bytes:
        raise ImageRejected(
            f"Image is too large: {len(data)} bytes exceeds the limit of {max_bytes} bytes.",
            status_code=413,
        )

    declared = normalize_media_type(declared_type)
    if declared is not None and declared not in ALLOWED_IMAGE_TYPES:
        raise ImageRejected(f"Unsupported image type: {declared}")

    sniffed = sniff_image_media_type(data)
    if sniffed is not None and sniffed not in ALLOWED_IMAGE_TYPES:
        raise ImageRejected(f"Unsupported image type: {sniffed}")
    if sniffed not in ALLOWED_IMAGE_TYPES:
        raise ImageRejected("Invalid image data.")
    if declared is not None and declared != sniffed:
        raise ImageRejected("Invalid image data.")

    _decode_image(data, sniffed=sniffed, max_pixels=max_pixels, max_dimension=max_dimension)
    from ai_agent.llm.client.types import ImageInput

    return ImageInput(data=data, media_type=sniffed)


def strip_image_metadata(image: ImageInput) -> ImageInput:
    """Bake EXIF orientation into pixels and drop metadata. Re-validates.

    Failure raises ImageRejected and does not return the original bytes.
    """
    from ai_agent.llm.client.types import ImageInput

    try:
        with _PILLOW_LOCK:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            previous_limit = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = DEFAULT_IMAGE_MAX_PIXELS
            opened = None
            transposed = None
            prepared = None
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", DecompressionBombWarning)
                    opened = Image.open(io.BytesIO(image.data))
                    lossless_webp = _webp_is_lossless(image.data, opened)
                    transposed = ImageOps.exif_transpose(opened)
                    prepared = _mode_for_save(
                        transposed,
                        image.media_type,
                        lossless_webp=lossless_webp,
                    )
                    payload = _save_without_metadata(
                        prepared,
                        image.media_type,
                        lossless_webp=lossless_webp and image.media_type == "image/webp",
                    )
            finally:
                Image.MAX_IMAGE_PIXELS = previous_limit
                for handle in (prepared, transposed, opened):
                    if handle is not None:
                        try:
                            handle.close()
                        except Exception:
                            logger.debug("Could not close an image during metadata strip", exc_info=True)
    except ImageRejected:
        raise
    except (UnidentifiedImageError, DecompressionBombError, DecompressionBombWarning, OSError, SyntaxError, ValueError) as exc:
        status = 413 if isinstance(exc, (DecompressionBombError, DecompressionBombWarning)) else 400
        raise ImageRejected("Invalid image data.", status_code=status) from exc

    # Re-validate. A failure here must not fall back to the original bytes.
    checked = validate_image_bytes(payload, declared_type=image.media_type)
    return ImageInput(data=checked.data, media_type=checked.media_type, attachment_id=image.attachment_id)


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


def normalize_media_type(value: str | None) -> str | None:
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


def _decode_image(
    data: bytes,
    *,
    sniffed: str,
    max_pixels: int,
    max_dimension: int,
) -> None:
    with _PILLOW_LOCK:
        ImageFile.LOAD_TRUNCATED_IMAGES = False
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
                except (UnidentifiedImageError, DecompressionBombError, DecompressionBombWarning, OSError, SyntaxError, ValueError) as exc:
                    _reject_decode(exc)
                finally:
                    if probe is not None:
                        probe.close()
                        probe = None
                try:
                    image = Image.open(io.BytesIO(data))
                    image.load()
                except (UnidentifiedImageError, DecompressionBombError, DecompressionBombWarning, OSError, SyntaxError, ValueError) as exc:
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
                if width > max_dimension or height > max_dimension or width * height > max_pixels:
                    raise ImageRejected(
                        f"Image dimensions {width}x{height} exceed the limit.",
                        status_code=413,
                    )
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit
            if image is not None:
                image.close()


def _reject_decode(exc: BaseException) -> None:
    status = 413 if isinstance(exc, (DecompressionBombError, DecompressionBombWarning)) else 400
    raise ImageRejected("Invalid image data.", status_code=status) from exc


def _webp_is_lossless(data: bytes, image: Image.Image) -> bool:
    if image.info.get("lossless"):
        return True
    return len(data) >= 16 and data[12:16] == b"VP8L"


def _mode_for_save(image: Image.Image, media_type: str, *, lossless_webp: bool) -> Image.Image:
    if media_type == "image/png" or (media_type == "image/webp" and lossless_webp):
        if image.mode == "P" and "transparency" in image.info:
            return image.convert("RGBA")
        if image.mode in {"1", "L", "LA", "P", "RGB", "RGBA"}:
            return image
        if "A" in image.mode:
            return image.convert("RGBA")
        return image.convert("RGB")
    if image.mode in {"RGB", "L"}:
        return image
    return image.convert("RGB")


def _save_without_metadata(image: Image.Image, media_type: str, *, lossless_webp: bool) -> bytes:
    buffer = io.BytesIO()
    if media_type == "image/jpeg":
        image.save(buffer, format="JPEG", quality=95, optimize=False)
    elif media_type == "image/png":
        image.save(buffer, format="PNG")
    elif media_type == "image/webp":
        if lossless_webp:
            image.save(buffer, format="WEBP", lossless=True)
        else:
            image.save(buffer, format="WEBP", quality=95)
    else:
        raise ImageRejected("Invalid image data.")
    return buffer.getvalue()
