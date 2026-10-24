"""Opaque ids for attachment paths. Same shape as execution-target ids."""

from __future__ import annotations

import re
from uuid import uuid4

ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def validate_id(value: str, *, what: str) -> str:
    cleaned = value.strip().lower()
    if not ID_RE.match(cleaned):
        raise ValueError(f"Invalid {what}")
    return cleaned


def new_attachment_id() -> str:
    return str(uuid4())
