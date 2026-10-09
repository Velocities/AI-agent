"""Grant and revoke monitoring admins on this deployment.

Run on the server that hosts the API, against the same SQLite file as
``ai-agent config access``. Use ``--service-db`` when the API uses the shared
deployment database.

Current behavior (revise with the store and the README "Monitoring admins"
section before finalizing):

* ``grant`` inserts the Supabase user id. Repeating it leaves the original row.
* ``revoke`` deletes that row. A missing id is an error so a typo is visible.
* ``list`` prints every monitoring admin. It does not list deployment-access rows.
* Agent approval and monitoring admin are independent.
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from ai_agent.config import Settings
from ai_agent.conversations.db import (
    database_display_path,
    database_url_for_admin_cli,
    open_stores_at,
)


def _service_db_parent() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--service-db",
        action="store_true",
        help=(
            "Use the deployment database (CONVERSATION_DATABASE from .env, or "
            "/var/lib/ai-agent/conversations.db)."
        ),
    )
    return common


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-agent config monitoring",
        description=(
            "Grant or revoke host-monitoring access for a Supabase user id "
            "(local SQLite). Run on the server that hosts the API."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    parent = _service_db_parent()
    sub.add_parser("list", parents=[parent], help="List monitoring admins.")
    grant = sub.add_parser(
        "grant",
        parents=[parent],
        help="Allow a Supabase user id to open host monitoring.",
    )
    grant.add_argument("user_id", help="Supabase user id (same id as config access).")
    revoke = sub.add_parser(
        "revoke",
        parents=[parent],
        help="Remove a Supabase user id from host monitoring.",
    )
    revoke.add_argument("user_id")

    args = parser.parse_args(argv)
    console = Console()
    settings = Settings()
    url = database_url_for_admin_cli(
        settings, service_db=getattr(args, "service_db", False)
    )
    console.print(f"[dim]Database: {database_display_path(url)}[/dim]\n")

    if args.command is None:
        parser.print_help()
        return 0

    try:
        _store, _access, _repo, admins = open_stores_at(url)
    except Exception as exc:
        console.print(f"[red]Could not open database:[/red] {exc}")
        console.print(
            "[dim]Use the same --service-db flag as "
            "ai-agent config access when the API uses the shared database.[/dim]"
        )
        return 1

    if args.command == "list":
        return _print_list(console, admins)
    if args.command == "grant":
        try:
            record, created = admins.grant(args.user_id)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        if created:
            console.print(f"[green]Granted[/green] monitoring admin to {record.user_id}.")
        else:
            console.print(f"[dim]{record.user_id} is already a monitoring admin.[/dim]")
        return 0
    if args.command == "revoke":
        try:
            removed = admins.revoke(args.user_id)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        if removed:
            console.print(f"[yellow]Revoked[/yellow] monitoring admin from {args.user_id.strip()}.")
            return 0
        console.print(f"[red]{args.user_id.strip()} is not a monitoring admin.[/red]")
        return 1

    parser.print_help()
    return 0


def _print_list(console: Console, admins) -> int:
    rows = admins.list_admins()
    if not rows:
        console.print("[dim]No monitoring admins in this database.[/dim]")
        return 0
    table = Table(title="Monitoring admins")
    table.add_column("user_id")
    table.add_column("granted")
    for row in rows:
        granted = row.created_at.isoformat(timespec="seconds")
        table.add_row(row.user_id, granted)
    console.print(table)
    return 0
