from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from rich.console import Console

_DEFAULT_SERVICE_USER = "ai"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-agent config service-access",
        description=(
            "Explain how the systemd service account relates to the Linux UID/GID "
            "that runs each session's commands and file operations."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("show", help="Print who runs local commands on this machine.")
    grant = sub.add_parser(
        "plan",
        help="Show how an approved Linux user runs local commands.",
    )
    grant.add_argument(
        "operator",
        nargs="?",
        default=os.environ.get("USER") or os.environ.get("LOGNAME") or "",
        help="Linux account to pass to access approve --run-as (default: current USER).",
    )

    args = parser.parse_args(argv)
    console = Console()
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "show":
        return _cmd_show(console)
    return _cmd_plan(console, args)


def _cmd_show(console: Console) -> int:
    user = _login_user()
    console.print("[bold]Who runs what[/bold]\n")
    console.print(
        "• [bold]Chat client[/bold] (`ai-agent` on your PC): talks to the HTTPS API only. "
        "It does [bold]not[/bold] run shell commands on your PC for server admin tasks."
    )
    console.print(
        "• [bold]API / agent loop[/bold] (on the model server): the systemd process stays "
        f"the [bold]User=[/bold] from `ai-agent.service` (usually [bold]{_DEFAULT_SERVICE_USER}[/bold]), "
        "and that account is not root."
    )
    console.print(
        "• [bold]Local execution target[/bold]: each approved session's commands and file "
        "operations run as the Linux UID/GID from `ai-agent config access approve "
        "… --run-as`. Unix permissions on those paths are the access control.\n"
    )
    if user:
        console.print(f"Your login on this machine (if SSH'd in): [bold]{user}[/bold]")
    unit_user = _systemd_service_user()
    if unit_user:
        console.print(f"Installed service User=: [bold]{unit_user}[/bold]")
    console.print(
        "\nA [italic]Permission denied[/italic] on a local command is that Linux account's "
        "own file permissions. See:\n"
        "  ai-agent config service-access plan"
    )
    return 0


def _cmd_plan(console: Console, args: argparse.Namespace) -> int:
    operator = (args.operator or "").strip()
    if not operator:
        console.print("[red]Pass OPERATOR_USER or set USER.[/red]")
        return 1
    repo = Path.cwd()
    service_user = _systemd_service_user() or _DEFAULT_SERVICE_USER
    home = Path(f"/home/{operator}")
    if not home.is_dir():
        home = Path.home()

    console.print(
        _format_plan(
            operator=operator,
            service_user=service_user,
            repo=repo,
            home=home,
        )
    )
    return 0


def _format_plan(
    *,
    operator: str,
    service_user: str,
    repo: Path,
    home: Path,
) -> str:
    lines = [
        f"Linux account for local commands: {operator} (home {home})",
        f"Service process user: {service_user} (stays this account; not root)",
        f"Checkout (cwd): {repo}",
        "",
        "Approve the Supabase user with this Linux account:",
        f"  ai-agent config access approve <user_id> --run-as {operator}",
        "",
        "The service keeps CAP_SETUID and CAP_SETGID and runs that session's commands",
        "and file operations with setpriv as this UID/GID. Concurrent users stay",
        "isolated because each session uses its own credentials. Access to files is",
        "that account's normal Unix permissions.",
        "",
        "After changing the unit, reinstall and restart:",
        "  sudo deploy/systemd/install.sh",
        "  sudo systemctl restart ai-agent",
        "",
        "Then ask the agent to run: id -u; id -g; whoami",
    ]
    return "\n".join(lines)


def _login_user() -> str:
    return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def _systemd_service_user() -> str | None:
    try:
        result = subprocess.run(
            ["systemctl", "show", "-p", "User", "--value", "ai-agent.service"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    value = result.stdout.strip()
    return value or None
