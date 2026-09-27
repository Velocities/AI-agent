from __future__ import annotations

import re

_LINUX_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def profile_from_jwt_payload(payload: dict) -> tuple[str, str]:
    """Return (email, display_name) from a verified Supabase access token payload."""
    email = payload.get("email")
    if not isinstance(email, str):
        email = ""
    email = email.strip()[:320]

    display = ""
    meta = payload.get("user_metadata")
    if isinstance(meta, dict):
        for key in ("full_name", "name", "preferred_username", "user_name"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                display = value.strip()[:200]
                break
    if not display and email:
        display = email.split("@", 1)[0][:200]
    return email, display


def suggest_linux_username(email: str) -> str | None:
    """Guess a Unix account name from an email local-part, or None if unsafe."""
    if not email or "@" not in email:
        return None
    local = email.split("@", 1)[0].lower()
    local = re.sub(r"[^a-z0-9._-]", "", local)
    local = local.replace(".", "_").replace("-", "_")
    local = re.sub(r"_+", "_", local).strip("_")
    if not local or not _LINUX_USER_RE.match(local):
        return None
    return local[:32]


def normalize_linux_username(value: str) -> str:
    name = value.strip().lower()
    if not _LINUX_USER_RE.match(name):
        raise ValueError(
            "Linux username must match [a-z_][a-z0-9_-]* (max 32 characters)."
        )
    return name
