"""Read the chat client's saved sign-in without importing the chat package."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OperatorStoredSession:
    access_token: str
    refresh_token: str
    expires_at: float


def _config_dir() -> Path:
    override = os.environ.get("AI_AGENT_CONFIG_DIR", "").strip()
    return Path(override) if override else Path.home() / ".config" / "ai-agent"


def _active_server_url() -> str | None:
    path = _config_dir() / "servers.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    active = payload.get("active")
    if isinstance(active, str) and active.strip():
        return active.strip()
    servers = payload.get("servers")
    if isinstance(servers, list) and servers:
        first = servers[0]
        if isinstance(first, dict):
            url = first.get("server_url")
            if isinstance(url, str) and url.strip():
                return url.strip()
    return None


def load_operator_session() -> OperatorStoredSession | None:
    url = _active_server_url()
    if url is None:
        return None
    import hashlib

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    path = _config_dir() / "sessions" / f"{digest}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    access = raw.get("access_token")
    refresh = raw.get("refresh_token")
    expires = raw.get("expires_at")
    if not isinstance(access, str) or not isinstance(refresh, str):
        return None
    if not isinstance(expires, (int, float)):
        return None
    return OperatorStoredSession(
        access_token=access,
        refresh_token=refresh,
        expires_at=float(expires),
    )


def session_is_fresh(session: OperatorStoredSession, *, skew: float = 60) -> bool:
    return session.expires_at - skew > time.time()