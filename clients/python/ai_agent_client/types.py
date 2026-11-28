from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageInput:
    """One image attached to the next chat message over the HTTP API."""

    data: bytes
    media_type: str
    attachment_id: str | None = None
