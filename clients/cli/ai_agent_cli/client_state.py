"""Saved agent servers, and the sign-in and chat id that belong to each one."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class StoredSession:
    access_token: str
    refresh_token: str
    expires_at: float


@dataclass(frozen=True)
class ServerConfig:
    server_url: str
    supabase_url: str
    supabase_publishable_key: str
    conversation_id: str | None = None


def normalize_server_url(raw: str) -> str:
    """Origin only, with no trailing slash. Raises ValueError when it is not a URL."""
    value = raw.strip().rstrip("/")
    if not value:
        raise ValueError("Enter the server URL.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(
            "Enter an http or https URL, for example https://agent.example.com."
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Enter the server address only, without a path.")
    if parsed.username or parsed.password:
        raise ValueError("Enter the server address without a username or password.")
    return value


def config_dir() -> Path:
    override = os.environ.get("AI_AGENT_CONFIG_DIR", "").strip()
    path = Path(override) if override else Path.home() / ".config" / "ai-agent"
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(stat.S_IRWXU)
    return path


def session_path_for(server_url: str) -> Path:
    """Session file for one agent-server origin. The hash is the scope key."""
    digest = hashlib.sha256(server_url.encode("utf-8")).hexdigest()
    folder = config_dir() / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(stat.S_IRWXU)
    return folder / f"{digest}.json"


def save_session_for(server_url: str, session: StoredSession) -> None:
    path = session_path_for(server_url)
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


def load_session_for(server_url: str) -> StoredSession | None:
    path = session_path_for(server_url)
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


def clear_session_for(server_url: str) -> None:
    path = session_path_for(server_url)
    if path.exists():
        path.unlink()


def save_session(session: StoredSession) -> None:
    """Write [session] onto the active server."""
    url = active_server_url()
    if url is None:
        raise ValueError("No server is saved.")
    save_session_for(url, session)


def load_session() -> StoredSession | None:
    """Sign-in for the active server, or None when nothing is saved or signed in."""
    url = active_server_url()
    if url is None:
        return None
    return load_session_for(url)


def clear_session() -> None:
    """Drop the active server's tokens. Other servers are left alone."""
    url = active_server_url()
    if url is None:
        return
    clear_session_for(url)


def session_is_fresh(session: StoredSession, *, skew: float = 60) -> bool:
    return session.expires_at - skew > time.time()


def active_server_url() -> str | None:
    config = load_server_config()
    if config is None:
        return None
    return config.server_url


def list_servers() -> list[ServerConfig]:
    servers, _active = _read_registry()
    return servers


def load_server_config() -> ServerConfig | None:
    servers, active = _read_registry()
    if not servers:
        return None
    if active is not None:
        for server in servers:
            if server.server_url == active:
                return server
    return servers[0]


def load_conversation_id() -> str | None:
    config = load_server_config()
    if config is None:
        return None
    return config.conversation_id


def save_conversation_id(conversation_id: str) -> None:
    active = load_server_config()
    if active is None:
        raise ValueError("No server is saved.")
    _save_registry(
        [
            _replace_conversation(server, conversation_id)
            if server.server_url == active.server_url
            else server
            for server in list_servers()
        ],
        active.server_url,
    )


def save_server_config(config: ServerConfig) -> None:
    """Insert or replace [config] and make it the active server."""
    updated: list[ServerConfig] = []
    replaced = False
    for server in list_servers():
        if server.server_url == config.server_url:
            updated.append(config)
            replaced = True
        else:
            updated.append(server)
    if not replaced:
        updated.append(config)
    _save_registry(updated, config.server_url)


def replace_server_list(servers: list[ServerConfig], active: str | None) -> None:
    _save_registry(servers, active)


def _registry_path() -> Path:
    return config_dir() / "servers.json"


def _read_registry() -> tuple[list[ServerConfig], str | None]:
    path = _registry_path()
    if not path.exists():
        return [], None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], None
    if not isinstance(payload, dict):
        return [], None
    raw_servers = payload.get("servers")
    servers: list[ServerConfig] = []
    if isinstance(raw_servers, list):
        for item in raw_servers:
            parsed = _parse_server(item)
            if parsed is not None:
                servers.append(parsed)
    active = payload.get("active")
    if not isinstance(active, str):
        active = None
    return servers, active


def _save_registry(servers: list[ServerConfig], active: str | None) -> None:
    path = _registry_path()
    path.write_text(
        json.dumps(
            {
                "active": active,
                "servers": [
                    {
                        "server_url": server.server_url,
                        "supabase_url": server.supabase_url,
                        "supabase_publishable_key": server.supabase_publishable_key,
                        "conversation_id": server.conversation_id,
                    }
                    for server in servers
                ],
            }
        ),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _parse_server(item: object) -> ServerConfig | None:
    if not isinstance(item, dict):
        return None
    conversation = item.get("conversation_id")
    if not isinstance(conversation, str) or not conversation:
        conversation = None
    try:
        return ServerConfig(
            server_url=normalize_server_url(str(item.get("server_url", ""))),
            supabase_url=_required_text(item, "supabase_url").rstrip("/"),
            supabase_publishable_key=_required_text(item, "supabase_publishable_key"),
            conversation_id=conversation,
        )
    except ValueError:
        return None


def _replace_conversation(server: ServerConfig, conversation_id: str | None) -> ServerConfig:
    return ServerConfig(
        server_url=server.server_url,
        supabase_url=server.supabase_url,
        supabase_publishable_key=server.supabase_publishable_key,
        conversation_id=conversation_id or None,
    )


def _required_text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Server configuration is missing {key}.")
    return value.strip()
