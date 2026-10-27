from __future__ import annotations

import sys
from dataclasses import dataclass

import httpx
from rich.console import Console

from ai_agent.api.client_config import CLIENT_CONFIG_PATH
from ai_agent_cli.client_state import (
    ServerConfig,
    clear_session_for,
    list_servers,
    load_server_config,
    load_session_for,
    normalize_server_url,
    replace_server_list,
    save_server_config,
)

_USAGE = (
    "usage: ai-agent server-url [--list | --remove URL | URL]\n"
    "\n"
    "Show the active AI server, list saved servers, add one, or remove one.\n"
    "The CLI downloads Supabase settings from that server.\n"
    "Each server keeps its own sign-in."
)


@dataclass(frozen=True)
class ServerUpdate:
    config: ServerConfig
    needs_login: bool


def fetch_client_config(server_url: str, *, client: httpx.Client | None = None) -> ServerConfig:
    """GET the public Supabase settings for this AI server."""
    origin = normalize_server_url(server_url)
    owns_client = client is None
    http = client or httpx.Client(timeout=15.0)
    try:
        response = http.get(f"{origin}{CLIENT_CONFIG_PATH}")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("Server did not return Supabase configuration.") from exc
    finally:
        if owns_client:
            http.close()
    if not isinstance(payload, dict):
        raise ValueError("Server did not return Supabase configuration.")
    return ServerConfig(
        server_url=origin,
        supabase_url=_required_text(payload, "supabase_url").rstrip("/"),
        supabase_publishable_key=_required_text(payload, "supabase_publishable_key"),
    )


def set_server_url(raw: str, *, client: httpx.Client | None = None) -> ServerUpdate:
    """Save [raw] and make it the active server.

    A server that was already saved keeps its sign-in and chat id. Those are
    dropped only when that same server's Supabase project changes. Other
    servers are not touched.
    """
    config = fetch_client_config(raw, client=client)
    previous = next(
        (server for server in list_servers() if server.server_url == config.server_url),
        None,
    )
    supabase_changed = previous is not None and (
        previous.supabase_url != config.supabase_url
        or previous.supabase_publishable_key != config.supabase_publishable_key
    )
    conversation_id = None if previous is None or supabase_changed else previous.conversation_id
    if supabase_changed:
        clear_session_for(config.server_url)
    stored = ServerConfig(
        server_url=config.server_url,
        supabase_url=config.supabase_url,
        supabase_publishable_key=config.supabase_publishable_key,
        conversation_id=conversation_id,
    )
    save_server_config(stored)
    return ServerUpdate(config=stored, needs_login=load_session_for(stored.server_url) is None)


def remove_server(raw: str) -> ServerConfig | None:
    """Forget [raw], including its sign-in. Returns the server that is active now."""
    origin = normalize_server_url(raw)
    servers = list_servers()
    if not any(server.server_url == origin for server in servers):
        raise ValueError("That server is not saved.")
    clear_session_for(origin)
    remaining = [server for server in servers if server.server_url != origin]
    active = load_server_config()
    next_url = None
    if remaining:
        next_url = remaining[0].server_url
        if active is not None and active.server_url != origin:
            next_url = active.server_url
    replace_server_list(remaining, next_url)
    return load_server_config()


def ensure_server_config(console: Console) -> ServerConfig | None:
    """Return the active server, or ask for one on the first run."""
    existing = load_server_config()
    if existing is not None:
        return existing
    console.print(
        "Enter the AI server URL. Example: https://agent.example.com "
        "or http://127.0.0.1:8000"
    )
    while True:
        try:
            raw = console.input("AI server URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return None
        if not raw:
            console.print("[red]A server URL is required.[/red]")
            continue
        try:
            return set_server_url(raw).config
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
        except httpx.HTTPError as exc:
            console.print(f"[red]Could not reach that server:[/red] {exc}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    console = Console()
    if any(arg in {"-h", "--help"} for arg in args):
        console.print(_USAGE)
        return 0
    if args == ["--list"]:
        _print_servers(console)
        return 0
    if args and args[0] == "--remove":
        if len(args) != 2:
            console.print(_USAGE)
            return 2
        try:
            remaining = remove_server(args[1])
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        console.print(f"Removed {normalize_server_url(args[1])}.")
        if remaining is None:
            console.print("No servers saved.")
        else:
            console.print(f"Using {remaining.server_url}.")
        return 0
    if len(args) > 1:
        console.print(_USAGE)
        return 2
    if not args:
        current = load_server_config()
        if current is None:
            console.print(
                "No server URL saved. Run [bold]ai-agent login[/bold] and enter one."
            )
            return 1
        console.print(current.server_url)
        return 0
    try:
        update = set_server_url(args[0])
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    except httpx.HTTPError as exc:
        console.print(f"[red]Could not reach that server:[/red] {exc}")
        return 1
    console.print(f"Using {update.config.server_url}.")
    if update.needs_login:
        console.print("Not signed in on this server. Run [bold]ai-agent login[/bold].")
    return 0


def _print_servers(console: Console) -> None:
    servers = list_servers()
    active = load_server_config()
    if not servers:
        console.print("No servers saved.")
        return
    for server in servers:
        mark = "*" if active is not None and server.server_url == active.server_url else " "
        console.print(f"{mark} {server.server_url}")


def _required_text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Server configuration is missing {key}.")
    return value.strip()
