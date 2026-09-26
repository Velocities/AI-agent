from __future__ import annotations

import argparse
from datetime import datetime

from rich.console import Console
from rich.table import Table

from ai_agent.config import Settings
from ai_agent.conversations.db import database_display_path, database_url, open_stores
from ai_agent.deployment.access import AccessStatus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-agent config access",
        description=(
            "Manage this deployment's access whitelist (local SQLite). "
            "Run on the server that hosts the API."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser(
        "list",
        help="List access rows (default: pending only).",
    )
    list_parser = sub.add_parser("list-all", help="List every access row.")
    list_parser  # register only
    approve = sub.add_parser("approve", help="Allow a Supabase user id to use this deployment.")
    approve.add_argument("user_id", help="Value from /api/me or the pending list.")
    deny = sub.add_parser("deny", help="Block a user id (approve later to undo).")
    deny.add_argument("user_id")
    sub.add_parser(
        "bootstrap-help",
        help="Print first-time admin steps for a fresh install.",
    )

    args = parser.parse_args(argv)
    console = Console()
    settings = Settings()
    db_path = database_display_path(database_url(settings))
    console.print(f"[dim]Database: {db_path}[/dim]\n")

    try:
        _store, access = open_stores(settings)
    except Exception as exc:
        console.print(f"[red]Could not open database:[/red] {exc}")
        return 1

    if args.command is None or args.command == "bootstrap-help":
        _print_bootstrap_help(console)
        return 0
    if args.command == "list":
        return _cmd_list(console, access, status=AccessStatus.PENDING)
    if args.command == "list-all":
        return _cmd_list(console, access, status=None)
    if args.command == "approve":
        record = access.approve(args.user_id.strip())
        console.print(
            f"[green]Approved[/green] {record.user_id} for this deployment."
        )
        return 0
    if args.command == "deny":
        record = access.deny(args.user_id.strip())
        console.print(f"[yellow]Denied[/yellow] {record.user_id} for this deployment.")
        return 0

    parser.print_help()
    return 0


def _cmd_list(console: Console, access, *, status: AccessStatus | None) -> int:
    rows = access.list_by_status(status)
    if not rows:
        label = status.value if status else "any"
        console.print(f"[dim]No {label} access rows.[/dim]")
        return 0
    table = Table(title="Deployment access")
    table.add_column("Status")
    table.add_column("User id")
    table.add_column("Created")
    table.add_column("Updated")
    for row in rows:
        table.add_row(
            row.status.value,
            row.user_id,
            _fmt(row.created_at),
            _fmt(row.updated_at),
        )
    console.print(table)
    return 0


def _fmt(when: datetime) -> str:
    return when.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _print_bootstrap_help(console: Console) -> None:
    console.print("[bold]First-time access setup[/bold]\n")
    console.print(
        "1. Start the API on this machine (systemd or [bold]ai-agent serve[/bold]).\n"
        "2. On your PC, run [bold]ai-agent login[/bold], then [bold]ai-agent[/bold] once.\n"
        "   The client will show a whitelist message — that creates a [bold]pending[/bold] row here.\n"
        "3. On this server:\n"
        "     ai-agent config access list\n"
        "     ai-agent config access approve <user_id>\n"
        "4. Run [bold]ai-agent[/bold] again on your PC.\n"
    )
    console.print(
        "[dim]To block someone: ai-agent config access deny <user_id>\n"
        "To undo a deny: ai-agent config access approve <user_id>[/dim]"
    )
