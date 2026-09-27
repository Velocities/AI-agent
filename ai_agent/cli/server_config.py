from __future__ import annotations

import json
import stat
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from rich.console import Console

from ai_agent.api.client_config import CLIENT_CONFIG_PATH
from ai_agent.cli.credentials import (
    clear_conversation_id,
    clear_session,
    config_dir,
    load_session,
)

_USAGE = (
    "usage: ai-agent server-url [URL]\n"
    "\n"
    "Show the saved AI server URL, or save a new one.\n"
    "The CLI downloads Supabase settings from that server.\n"
    "A different URL signs you out; run ai-agent login again."
)


@dataclass(frozen=True)
class ServerConfig:
    server_url: str
    supabase_url: str
    supabase_publishable_key: str


@dataclass(frozen=True)
class ServerUpdate:
    config: ServerConfig
    signed_out: bool


def server_config_path():
    return config_dir() / "server.json"


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


def load_server_config() -> ServerConfig | None:
    path = server_config_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return ServerConfig(
            server_url=normalize_server_url(str(payload.get("server_url", ""))),
            supabase_url=_required_text(payload, "supabase_url").rstrip("/"),
            supabase_publishable_key=_required_text(payload, "supabase_publishable_key"),
        )
    except ValueError:
        return None


def save_server_config(config: ServerConfig) -> None:
    path = server_config_path()
    path.write_text(
        json.dumps(
            {
                "server_url": config.server_url,
                "supabase_url": config.supabase_url,
                "supabase_publishable_key": config.supabase_publishable_key,
            }
        ),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


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
    """Save [raw] after downloading its Supabase settings.

    A different server URL, or a different Supabase project on the same URL,
    drops the saved sign-in and the current chat id.
    """
    config = fetch_client_config(raw, client=client)
    previous = load_server_config()
    url_changed = previous is not None and previous.server_url != config.server_url
    supabase_changed = previous is not None and (
        previous.supabase_url != config.supabase_url
        or previous.supabase_publishable_key != config.supabase_publishable_key
    )
    save_server_config(config)
    signed_out = url_changed or supabase_changed
    if signed_out:
        clear_session()
        clear_conversation_id()
    return ServerUpdate(config=config, signed_out=signed_out)


def ensure_server_config(console: Console) -> ServerConfig | None:
    """Return the saved server, or ask for one on the first run."""
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
    if update.signed_out:
        console.print(f"Server URL updated to {update.config.server_url}.")
        console.print("Signed out. Run [bold]ai-agent login[/bold] to sign in again.")
    else:
        console.print(f"Server URL saved: {update.config.server_url}")
        if load_session() is None:
            console.print("Run [bold]ai-agent login[/bold] to sign in.")
    return 0


def _required_text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Server configuration is missing {key}.")
    return value.strip()
