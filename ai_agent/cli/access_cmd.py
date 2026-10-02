from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ai_agent.config import Settings
from ai_agent.conversations.db import (
    database_display_path,
    database_url,
    open_stores_at,
    service_user_database_path,
    service_user_database_url,
    shared_deployment_database_path,
)
from ai_agent.deployment.access import AccessStatus


def _service_db_parent() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--service-db",
        action="store_true",
        help="Use the systemd service user's database (when CONVERSATION_DATABASE is unset).",
    )
    return common


def main(argv: list[str] | None = None) -> int:
    service_db_parent = _service_db_parent()
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
        parents=[service_db_parent],
        help="List access rows (default: pending only).",
    )
    sub.add_parser(
        "list-all",
        parents=[service_db_parent],
        help="List every access row.",
    )
    approve = sub.add_parser(
        "approve",
        parents=[service_db_parent],
        help="Allow a Supabase user id to use this deployment.",
    )
    approve.add_argument("user_id", help="Value from /api/me or the pending list.")
    approve.add_argument(
        "--run-as",
        metavar="LINUX_USER",
        help=(
            "Linux account for local command execution (defaults from email when safe)."
        ),
    )
    deny = sub.add_parser(
        "deny",
        parents=[service_db_parent],
        help="Block a user id (approve later to undo).",
    )
    deny.add_argument("user_id")
    sub.add_parser(
        "bootstrap-help",
        parents=[service_db_parent],
        help="Print first-time admin steps for a fresh install.",
    )

    args = parser.parse_args(argv)
    console = Console()
    settings = Settings()
    url = _database_url_for_cli(settings, service_db=getattr(args, "service_db", False))
    db_path = database_display_path(url)

    if args.command == "bootstrap-help":
        console.print(f"[dim]Database: {db_path}[/dim]\n")
        _print_bootstrap_help(console)
        return 0

    console.print(f"[dim]Database: {db_path}[/dim]\n")

    try:
        _store, access, _repo = open_stores_at(url)
    except PermissionError:
        console.print(
            "[red]Permission denied[/red] reading the service database.\n"
            "Run as the service user from the repo:\n\n"
            "  sudo -u ai bash -c 'cd "
            f"{Path.cwd()} && ./.venv/bin/ai-agent config access list'\n"
        )
        _print_shared_db_permission_hint(console, Path(db_path))
        return 1
    except OSError as exc:
        if _looks_like_sqlite_open_failure(exc):
            console.print(f"[red]Could not open database:[/red] {exc}")
            _print_shared_db_permission_hint(console, Path(db_path))
            return 1
        console.print(f"[red]Could not open database:[/red] {exc}")
        return 1
    except Exception as exc:
        if _looks_like_sqlite_open_failure(exc):
            console.print(f"[red]Could not open database:[/red] {exc}")
            _print_shared_db_permission_hint(console, Path(db_path))
            return 1
        console.print(f"[red]Could not open database:[/red] {exc}")
        return 1

    if args.command is None:
        _print_bootstrap_help(console)
        return 0
    if args.command == "list":
        return _run_list(console, access, settings, status=AccessStatus.PENDING)
    if args.command == "list-all":
        return _run_list(console, access, settings, status=None)
    if args.command == "approve":
        try:
            record = access.approve(
                args.user_id.strip(),
                linux_username=getattr(args, "run_as", None),
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        label = record.display_name or record.email or record.user_id
        console.print(
            f"[green]Approved[/green] {label} "
            f"(commands run as [bold]{record.linux_username}[/bold])."
        )
        return 0
    if args.command == "deny":
        record = access.deny(args.user_id.strip())
        console.print(f"[yellow]Denied[/yellow] {record.user_id} for this deployment.")
        return 0

    parser.print_help()
    return 0


def _run_list(
    console: Console,
    access,
    settings: Settings,
    *,
    status: AccessStatus | None,
) -> int:
    try:
        return _cmd_list(console, access, settings, status=status)
    except Exception as exc:
        if _looks_like_sqlite_open_failure(exc):
            console.print(f"[red]Could not open database:[/red] {exc}")
            _print_shared_db_permission_hint(
                console, Path(database_display_path(database_url(settings)))
            )
            return 1
        raise


def _database_url_for_cli(settings: Settings, *, service_db: bool) -> str:
    if service_db:
        return service_user_database_url()
    return database_url(settings)


def _cmd_list(
    console: Console,
    access,
    settings: Settings,
    *,
    status: AccessStatus | None,
) -> int:
    rows = access.list_by_status(status)
    if rows:
        _print_table(console, rows)
        return 0

    label = status.value if status else "any"
    console.print(f"[dim]No {label} access rows in this database.[/dim]")
    if settings.conversation_database.strip():
        return 0

    fallback_path = service_user_database_path()
    primary_path = Path(database_display_path(database_url(settings)))
    if not _path_readable(fallback_path):
        _print_database_mismatch_hint(console, settings)
        return 0
    if fallback_path.resolve() != primary_path.resolve():
        try:
            _store, fallback_access, _repo = open_stores_at(service_user_database_url())
        except OSError:
            _print_database_mismatch_hint(console, settings)
            return 0
        fallback_rows = fallback_access.list_by_status(status)
        if fallback_rows:
            console.print(
                f"\n[yellow]Found rows in the service database[/yellow] "
                f"({fallback_path}):\n"
                "The API runs as user [bold]ai[/bold]; your shell used a different "
                "default path. Fix [bold].env[/bold] on the server:\n\n"
                f"  CONVERSATION_DATABASE=sqlite:///{shared_deployment_database_path()}\n\n"
                "Then restart [bold]ai-agent[/bold] and use the same path for admin:\n"
                "  ai-agent config access list\n"
                "Or for now:\n"
                "  ai-agent config access list --service-db\n"
            )
            _print_table(console, fallback_rows)
            return 0
    _print_database_mismatch_hint(console, settings)
    return 0


def _path_readable(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _print_database_mismatch_hint(console: Console, settings: Settings) -> None:
    if settings.conversation_database.strip():
        return
    if os.environ.get("USER") in {None, "", "ai"}:
        return
    console.print(
        "\n[dim]If the API runs under systemd as user ai, set a shared path in "
        ".env (then restart the service):\n"
        f"  CONVERSATION_DATABASE=sqlite:///{shared_deployment_database_path()}\n"
        "Or list the service copy once:\n"
        "  ai-agent config access list --service-db[/dim]"
    )


def _print_table(console: Console, rows) -> None:
    table = Table(title="Deployment access")
    table.add_column("Status")
    table.add_column("Name")
    table.add_column("Email")
    table.add_column("Linux user")
    table.add_column("User id")
    table.add_column("Created")
    for row in rows:
        table.add_row(
            row.status.value,
            row.display_name or "—",
            row.email or "—",
            row.linux_username or "—",
            row.user_id,
            _fmt(row.created_at),
        )
    console.print(table)


def _fmt(when: datetime) -> str:
    return when.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _looks_like_sqlite_open_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "unable to open database file" in text or "readonly database" in text


def _print_shared_db_permission_hint(console: Console, db_path: Path) -> None:
    shared = shared_deployment_database_path()
    if db_path.resolve() != shared.resolve():
        return
    console.print(
        "\n[dim]SQLite needs group write on the directory (770) for WAL files, and "
        "660 on the database and sidecars. The service unit should use "
        "StateDirectoryMode=0770 and UMask=0007.\n\n"
        "  sudo usermod -aG ai $USER\n"
        "  # log out and back in, or: newgrp ai\n"
        f"  sudo chown ai:ai {shared.parent} {shared.parent}/{shared.name}*\n"
        f"  sudo chmod 2770 {shared.parent}\n"
        f"  sudo chmod 660 {shared.parent}/{shared.name}*\n"
        "  sudo systemctl daemon-reload && sudo systemctl restart ai-agent\n\n"
        "Or run access commands as the service user:\n"
        "  sudo -u ai bash -c 'cd "
        f"{Path.cwd()} && ./.venv/bin/ai-agent config access list'[/dim]"
    )


def _print_bootstrap_help(console: Console) -> None:
    console.print("[bold]First-time access setup[/bold]\n")
    console.print(
        "1. In [bold].env[/bold] on the server, set one shared database path "
        "(systemd user [bold]ai[/bold] and your admin shell must match):\n"
        f"     CONVERSATION_DATABASE=sqlite:///{shared_deployment_database_path()}\n"
        "2. Restart the API: [bold]sudo systemctl restart ai-agent[/bold]\n"
        "3. On your PC: [bold]ai-agent login[/bold], then [bold]ai-agent[/bold] once "
        "(whitelist message creates a pending row).\n"
        "4. On the server:\n"
        "     ai-agent config access list\n"
        "     ai-agent config access approve <user_id> --run-as <linux_user>\n"
        "5. Run [bold]ai-agent[/bold] again on your PC.\n"
    )
    console.print(
        "[dim]If you have not set CONVERSATION_DATABASE yet, pending rows may only "
        "appear under --service-db until you unify the path.\n"
        "Deny: ai-agent config access deny <user_id>\n"
        "Undo deny: ai-agent config access approve <user_id>[/dim]"
    )
