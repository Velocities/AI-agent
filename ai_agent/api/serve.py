from __future__ import annotations

import logging

import uvicorn
from rich.console import Console

from ai_agent.api.app import create_app
from ai_agent.config import Settings
from ai_agent.conversations.db import database_display_path, database_url, open_stores

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class PublicBindError(ValueError):
    """Raised when ai-agent-serve is asked to listen beyond loopback."""


def assert_loopback_bind(host: str, port: int) -> None:
    """Refuse any listen address the Cloudflare Tunnel does not need."""
    normalized = host.strip().lower()
    if normalized not in LOOPBACK_HOSTS:
        raise PublicBindError(
            "API_BIND_HOST must be a loopback address "
            f"(127.0.0.1, localhost, or ::1), not {host!r}. "
            "HTTPS is provided by the Cloudflare Tunnel to this process."
        )
    if port < 1 or port > 65535:
        raise PublicBindError(
            f"API_BIND_PORT must be between 1 and 65535, not {port}."
        )


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    console = Console()
    settings = Settings()
    _configure_logging(settings.agent_log_level)

    try:
        assert_loopback_bind(settings.api_bind_host, settings.api_bind_port)
    except PublicBindError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    if not settings.supabase_url.strip():
        logger.warning(
            "SUPABASE_URL is unset. /health will answer, /api/me will return 503."
        )

    try:
        store, access_store = open_stores(settings)
    except Exception as exc:
        console.print(f"[red]Could not open conversation database:[/red] {exc}")
        return 1

    host = settings.api_bind_host.strip()
    port = settings.api_bind_port
    display_host = "127.0.0.1" if host.lower() == "localhost" else host
    console.print("[bold]AI Agent API[/bold]")
    console.print(f"Listening: http://{display_host}:{port}")
    if settings.supabase_url.strip():
        console.print("Auth: Supabase access token")
    else:
        console.print("[yellow]Auth: not configured[/yellow] (set SUPABASE_URL)")
    console.print(f"Conversations: {database_display_path(database_url(settings))}")
    console.print(
        "[dim]Point the Cloudflare Tunnel at this address. "
        "The database file is not served. Ctrl+C to stop.[/dim]\n"
    )

    uvicorn.run(
        create_app(settings, store=store, access_store=access_store),
        host=host,
        port=port,
        log_level=settings.agent_log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
