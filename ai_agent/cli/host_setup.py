from __future__ import annotations

import argparse
from getpass import getuser
from pathlib import Path

from rich.console import Console

from ai_agent.cli.confirm import confirm
from ai_agent.llm.host_setup import (
    linux_authorized_keys_path,
    merge_authorized_key,
    normalize_public_key,
    ollama_is_listening,
    restart_sshd,
    restrict_windows_admin_key_acl,
    windows_account_is_elevated,
    windows_authorized_keys_path,
)


def _read_public_key(args: argparse.Namespace) -> str:
    if args.public_key_file:
        return normalize_public_key(Path(args.public_key_file).read_text(encoding="utf-8"))
    if args.public_key:
        return normalize_public_key(args.public_key)
    raise ValueError("Pass --public-key-file or --public-key.")


def run_host_setup(console: Console, args: argparse.Namespace) -> int:
    try:
        public_key = _read_public_key(args)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    home = Path.home()
    if args.linux:
        key_path = linux_authorized_keys_path(home)
        admin_file = False
    else:
        admin_file = args.admin or windows_account_is_elevated()
        key_path = windows_authorized_keys_path(home=home, admin_account=admin_file)

    console.print("[bold]AI Agent GPU host setup[/bold]")
    console.print(f"User: {getuser()}")
    console.print(f"Authorized keys file: {key_path}")
    console.print(f"Public key: {public_key[:48]}...")
    if not args.linux and admin_file:
        console.print(
            "[dim]Administrator account: using administrators_authorized_keys "
            "(the per-user file is ignored by Windows OpenSSH).[/dim]"
        )
    if not confirm(console, "Install this key and restart sshd"):
        console.print("Cancelled.")
        return 1

    try:
        added = merge_authorized_key(key_path, public_key)
    except OSError as exc:
        console.print(
            f"[red]Could not write {key_path}:[/red] {exc}\n"
            "On Windows, run this command in an Administrator PowerShell."
        )
        return 1

    if added:
        console.print(f"Appended key to {key_path}")
    else:
        console.print(f"Key already present in {key_path}")

    if admin_file:
        restrict_windows_admin_key_acl(key_path)

    ok, detail = restart_sshd()
    if ok:
        console.print(detail)
    else:
        console.print(f"[yellow]{detail}[/yellow]")

    if ollama_is_listening():
        console.print("[green]Ollama is listening on 127.0.0.1:11434.[/green]")
    else:
        console.print(
            "[yellow]Ollama is not reachable on 127.0.0.1:11434. "
            "Start the Ollama app (do not change the port).[/yellow]"
        )

    console.print(
        "\nOn the laptop, from the agent repo:\n"
        "  ai-agent config remote-provider test"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-agent host-setup",
        description="Install the laptop sandbox public key on this GPU machine.",
    )
    parser.add_argument("--public-key", help="Single OpenSSH public key line.")
    parser.add_argument(
        "--public-key-file",
        help="File containing that one public key line.",
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Force the Windows administrators_authorized_keys file.",
    )
    parser.add_argument(
        "--linux",
        action="store_true",
        help="Use ~/.ssh/authorized_keys (Linux GPU host).",
    )
    args = parser.parse_args(argv)
    return run_host_setup(Console(), args)
