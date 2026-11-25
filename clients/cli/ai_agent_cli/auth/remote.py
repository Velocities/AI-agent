from __future__ import annotations

from dataclasses import dataclass

import httpx
from rich.console import Console

from ai_agent_cli.client_state import (
    ServerConfig,
    load_session_for,
    save_session_for,
    session_is_fresh,
)
from ai_agent_cli.login import refresh_session


def bearer_token_for_remote(config: ServerConfig, console: Console) -> str | None:
    session = load_session_for(config.server_url)
    if session is None:
        console.print(
            f"Not signed in to {config.server_url}. Run [bold]ai-agent-chat login[/bold]."
        )
        return None
    if session_is_fresh(session):
        return session.access_token
    if not config.supabase_url.strip() or not config.supabase_publishable_key.strip():
        console.print("[red]The saved session expired. Run ai-agent-chat login.[/red]")
        return None
    try:
        refreshed = refresh_session(
            supabase_url=config.supabase_url,
            anon_key=config.supabase_publishable_key,
            refresh_token=session.refresh_token,
        )
    except httpx.HTTPError:
        console.print("[red]Could not refresh sign-in. Run ai-agent-chat login.[/red]")
        return None
    save_session_for(config.server_url, refreshed)
    return refreshed.access_token


@dataclass
class RemoteSupabaseAuth:
    console: Console

    def bearer_token(self, config: ServerConfig) -> str | None:
        return bearer_token_for_remote(config, self.console)