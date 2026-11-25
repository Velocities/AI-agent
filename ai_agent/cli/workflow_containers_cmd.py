"""List and remove workflow Docker containers on the deployment host."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from ai_agent.cli.confirm import confirm
from ai_agent.config import Settings
from ai_agent.conversations.db import (
    database_display_path,
    database_url_for_admin_cli,
    open_stores_at,
)
from ai_agent.workflows.admin_containers import (
    StateFilter,
    attach_conversation_hints,
    format_created,
    list_workflow_containers,
    remove_workflow_containers,
)


def _service_db_parent() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--service-db",
        action="store_true",
        help=(
            "Attach chat title and workflow name from the deployment database "
            "(CONVERSATION_DATABASE from .env, or /var/lib/ai-agent/conversations.db)."
        ),
    )
    return common


def main(argv: list[str] | None = None) -> int:
    parent = _service_db_parent()
    parser = argparse.ArgumentParser(
        prog="ai-agent config workflow-containers",
        description=(
            "List or remove workflow containers (names wf…). "
            "Run on the server with permission to run docker. "
            "This does not go through the API Docker broker."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser(
        "list",
        parents=[parent],
        help="Show workflow containers and their Docker state.",
    )
    list_parser.add_argument(
        "--state",
        choices=("all", "running", "stopped", "dead"),
        default="all",
        help=(
            "Filter rows: running (sleeping workload), stopped "
            "(exited/created/paused/restarting), or dead only."
        ),
    )

    rm_parser = sub.add_parser(
        "rm",
        parents=[parent],
        help="Remove one or more workflow containers (docker rm -f).",
    )
    rm_parser.add_argument(
        "names",
        nargs="*",
        metavar="NAME",
        help="Container name (wf…). Omit with --all.",
    )
    rm_parser.add_argument(
        "--all",
        action="store_true",
        help="Remove every workflow container that matches --state.",
    )
    rm_parser.add_argument(
        "--state",
        choices=("all", "running", "stopped", "dead"),
        default="all",
        help="With --all, only remove containers in this state (default: all).",
    )
    rm_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt when using --all.",
    )

    args = parser.parse_args(argv)
    console = Console()

    if args.command is None:
        parser.print_help()
        return 0

    engine = _optional_engine(console, args)
    if args.command == "list":
        return _cmd_list(console, state=args.state, engine=engine)
    if args.command == "rm":
        return _cmd_rm(
            console,
            names=list(args.names),
            remove_all=args.all,
            state=args.state,
            assume_yes=args.yes,
            engine=engine,
        )
    parser.print_help()
    return 0


def _optional_engine(console: Console, args):
    if not getattr(args, "service_db", False):
        return None
    settings = Settings()
    url = database_url_for_admin_cli(settings, service_db=True)
    console.print(f"[dim]Database: {database_display_path(url)}[/dim]\n")
    try:
        _store, _access, _repo, _admins = open_stores_at(url)
    except (PermissionError, OSError) as exc:
        console.print(f"[yellow]Could not open database for hints:[/yellow] {exc}")
        return None
    return _store.engine


def _cmd_list(console: Console, *, state: StateFilter, engine) -> int:
    try:
        rows = list_workflow_containers(state=state)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        console.print(
            "\n[dim]Run on the server as a user that can call docker "
            "(often root or a member of the docker group).[/dim]"
        )
        return 1
    if engine is not None:
        rows = attach_conversation_hints(rows, engine=engine)

    if not rows:
        console.print("[dim]No workflow containers match this filter.[/dim]")
        return 0

    table = Table(title="Workflow containers", show_lines=False)
    table.add_column("State", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("Image", overflow="fold")
    table.add_column("Status", overflow="fold")
    table.add_column("Created", no_wrap=True)
    if engine is not None:
        table.add_column("Workflow", no_wrap=True)
        table.add_column("Chat", overflow="fold")

    for row in rows:
        cells = [
            _state_cell(row.state_label),
            row.name,
            row.image,
            row.status or row.state,
            format_created(row.created),
        ]
        if engine is not None:
            cells.append(row.workflow_name or "—")
            cells.append(row.chat_title or row.conversation_id_hint or "—")
        table.add_row(*cells)

    console.print(table)
    console.print(
        "\n[dim]State meanings: [bold]running[/bold] = container up (sleep infinity); "
        "[bold]exited[/bold] = stopped; [bold]dead[/bold] = removed from disk in a bad state. "
        "Removing a container does not delete /work files on the host bind mount.[/dim]"
    )
    return 0


def _state_cell(label: str) -> str:
    if label == "running":
        return "[green]running[/green]"
    if label == "exited":
        return "[yellow]exited[/yellow]"
    if label == "dead":
        return "[red]dead[/red]"
    return label


def _cmd_rm(
    console: Console,
    *,
    names: list[str],
    remove_all: bool,
    state: StateFilter,
    assume_yes: bool,
    engine,
) -> int:
    if remove_all and names:
        console.print("[red]Pass container names or --all, not both.[/red]")
        return 2
    if not remove_all and not names:
        console.print("[red]Give at least one NAME or use --all.[/red]")
        return 2

    try:
        if remove_all:
            preview = list_workflow_containers(state=state)
            if engine is not None:
                preview = attach_conversation_hints(preview, engine=engine)
            if not preview:
                console.print("[dim]Nothing to remove for this filter.[/dim]")
                return 0
            console.print(f"Would remove {len(preview)} workflow container(s):")
            for row in preview:
                extra = ""
                if row.workflow_name:
                    extra = f" ({row.workflow_name})"
                console.print(f"  {row.name}{extra} [{row.state_label}]")
            if not assume_yes and not confirm(
                console, "Remove these workflow containers"
            ):
                console.print("[yellow]Cancelled.[/yellow]")
                return 0
            removed = remove_workflow_containers(
                [],
                all_workflows=True,
                state=state,
                containers=preview,
            )
        else:
            removed = remove_workflow_containers(names)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    console.print(f"[green]Removed[/green] {len(removed)} container(s).")
    for name in removed:
        console.print(f"  {name}")
    console.print(
        "[dim]Chats still exist in SQLite; users may rebuild a container on the next turn.[/dim]"
    )
    return 0