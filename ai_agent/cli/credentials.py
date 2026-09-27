from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StoredSession:
    access_token: str
    refresh_token: str
    expires_at: float


def config_dir() -> Path:
    override = os.environ.get("AI_AGENT_CONFIG_DIR", "").strip()
    path = Path(override) if override else Path.home() / ".config" / "ai-agent"
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(stat.S_IRWXU)
    return path


def session_path() -> Path:
    return config_dir() / "session.json"


def client_state_path() -> Path:
    return config_dir() / "client.json"


def save_session(session: StoredSession) -> None:
    path = session_path()
    path.write_text(
        json.dumps(
            {
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "expires_at": session.expires_at,
            }
        ),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def load_session() -> StoredSession | None:
    path = session_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires = payload.get("expires_at")
    if not isinstance(access, str) or not isinstance(refresh, str):
        return None
    if not isinstance(expires, (int, float)):
        expires = 0
    return StoredSession(
        access_token=access,
        refresh_token=refresh,
        expires_at=float(expires),
    )


def clear_session() -> None:
    path = session_path()
    if path.exists():
        path.unlink()


def session_is_fresh(session: StoredSession, *, skew: float = 60) -> bool:
    return session.expires_at - skew > time.time()


def load_conversation_id() -> str | None:
    path = client_state_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("conversation_id")
    return value if isinstance(value, str) and value else None


def save_conversation_id(conversation_id: str) -> None:
    path = client_state_path()
    path.write_text(
        json.dumps({"conversation_id": conversation_id}),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
