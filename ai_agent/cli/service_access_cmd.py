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
            "Explain how the systemd service user relates to shell command execution, "
            "and print grant commands for an operator account."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("show", help="Print who runs local commands on this machine.")
    grant = sub.add_parser(
        "plan",
        help="Print sudo commands to let the service user access an operator's files.",
    )
    grant.add_argument(
        "operator",
        nargs="?",
        default=os.environ.get("USER") or os.environ.get("LOGNAME") or "",
        help="Linux login that owns the checkout (default: current USER).",
    )
    grant.add_argument(
        "--list-home",
        action="store_true",
        help="Include --list-home in the suggested grant-access.sh command.",
    )
    grant.add_argument(
        "--read",
        action="append",
        default=[],
        metavar="PATH",
        help="Extra paths for --read (repeatable).",
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
        "• [bold]API / agent loop[/bold] (on the model server): runs as the systemd "
        f"[bold]User=[/bold] from `ai-agent.service` (usually [bold]{_DEFAULT_SERVICE_USER}[/bold])."
    )
    console.print(
        "• [bold]Local execution target[/bold]: shell commands run as that same OS user on "
        "the server, with policy limits — not as your Discord/Supabase identity.\n"
    )
    if user:
        console.print(f"Your login on this machine (if SSH'd in): [bold]{user}[/bold]")
    unit_user = _systemd_service_user()
    if unit_user:
        console.print(f"Installed service User=: [bold]{unit_user}[/bold]")
    console.print(
        "\nIf commands fail with [italic]Permission denied[/italic] under another user's home, "
        "that is normal until you grant ACLs or run the service as that user. See:\n"
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

    parts = ["sudo", "deploy/systemd/grant-access.sh", operator]
    if args.list_home:
        parts.append("--list-home")
    for path in args.read:
        parts.extend(["--read", path])
    grant_cmd = " ".join(parts)

    console.print(
        _format_plan(
            operator=operator,
            service_user=service_user,
            repo=repo,
            grant_cmd=grant_cmd,
            home=home,
        )
    )
    return 0


def _format_plan(
    *,
    operator: str,
    service_user: str,
    repo: Path,
    grant_cmd: str,
    home: Path,
) -> str:
    lines = [
        f"Operator login: {operator} (home {home})",
        f"Service / command user: {service_user}",
        f"Checkout (cwd): {repo}",
        "",
        "Recommended (keeps dedicated service user, grants read access):",
        f"  {grant_cmd}",
        "",
        "That script installs traverse ACLs, read access under ~/gh_repos by default, "
        "and optional --list-home to ls the operator home directory.",
        "",
        "Alternative (simple personal server — service runs as your login):",
        f"  sudo AI_AGENT_SERVICE_USER={operator} deploy/systemd/install.sh",
        "  sudo systemctl restart ai-agent",
        "",
        "Then ask the agent to run: id, pwd, whoami — it should report your chosen user.",
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
