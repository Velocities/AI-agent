"""Process environment for the Discord bot."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    public_url: str
    oauth_host: str
    oauth_port: int
    state_path: Path
    guild_id: int | None


def load_config(environ: Mapping[str, str] | None = None) -> DiscordConfig:
    env = os.environ if environ is None else environ
    token = env.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Set DISCORD_BOT_TOKEN to the Discord bot token.")
    public = env.get("DISCORD_PUBLIC_URL", "").strip()
    if not public:
        raise ValueError(
            "Set DISCORD_PUBLIC_URL to the https origin where this bot's "
            "/callback redirect is reachable."
        )
    redirect_url(public)
    host = env.get("DISCORD_OAUTH_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port_text = env.get("DISCORD_OAUTH_PORT", "53683").strip() or "53683"
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError(f"DISCORD_OAUTH_PORT is not a port: {port_text}") from exc
    if port < 0 or port > 65535:
        raise ValueError(f"DISCORD_OAUTH_PORT is not a port: {port_text}")
    state = env.get("AI_AGENT_DISCORD_STATE", "").strip()
    path = Path(state) if state else Path.home() / ".config" / "ai-agent-discord" / "state.json"
    guild_text = env.get("DISCORD_GUILD_ID", "").strip()
    guild_id = None
    if guild_text:
        if not guild_text.isdigit():
            raise ValueError("DISCORD_GUILD_ID must be a numeric server id.")
        guild_id = int(guild_text)
    return DiscordConfig(
        token=token,
        public_url=public.rstrip("/"),
        oauth_host=host,
        oauth_port=port,
        state_path=path,
        guild_id=guild_id,
    )


def redirect_url(public_url: str) -> str:
    origin = public_url.strip().rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("DISCORD_PUBLIC_URL must be an http or https origin.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("DISCORD_PUBLIC_URL must be the origin only, without a path.")
    if parsed.username or parsed.password:
        raise ValueError("DISCORD_PUBLIC_URL must not include a username or password.")
    return f"{origin}/callback"
