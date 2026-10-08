"""Per-user execution targets (SQLite + SecureKeyStore). See docs/execution-targets.md."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from ai_agent.cli.confirm import confirm
from ai_agent.cli.target_subject import TargetSubjectError, resolve_subject_user_id
from ai_agent.config import Settings
from ai_agent.cli.access_cmd import (
    _looks_like_sqlite_open_failure,
    _print_shared_db_permission_hint,
)
from ai_agent.conversations.db import (
    database_display_path,
    database_url_for_admin_cli,
    open_stores_at,
)
from ai_agent.deployment.access import AccessStatus
from ai_agent.execution_targets.repository import UserExecutionTargetRepository
from ai_agent.execution_targets.secure_key_store import OSSecureKeyStore
from ai_agent.execution_targets.store import RESERVED_LOCAL_NAME, TargetConfigError
from ai_agent.execution_targets.yaml_import import import_legacy_yaml
from ai_agent.llm.ssh_sandbox import (
    append_known_hosts,
    list_ssh_host_aliases,
    read_public_key,
    resolve_user_ssh_host,
    scan_host_keys,
)


def _prompt(console: Console, label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = console.input(f"{label}{suffix}: ").strip()
    return value or default


def _open_repo(settings: Settings, *, service_db: bool) -> tuple[str, UserExecutionTargetRepository, object]:
    url = database_url_for_admin_cli(settings, service_db=service_db)
    _store, access, repo, _admins = open_stores_at(url)
    return url, repo, access


def cmd_list(
    console: Console,
    repo: UserExecutionTargetRepository,
    user_id: str,
    db_path: str,
) -> int:
    console.print(f"[bold]Execution targets[/bold] for user [dim]{user_id}[/dim]")
    console.print(f"[dim]Database: {db_path}[/dim]\n")
    records = repo.list_for_user(user_id)
    console.print(f"  Default when omitted: {RESERVED_LOCAL_NAME} (this machine)")
    console.print(f"  - {RESERVED_LOCAL_NAME} (local) — This machine (approved Linux user)")
    for rec in records:
        extra = ""
        if rec.type == "ssh":
            extra = f" ssh://{rec.spec.get('user')}@{rec.spec.get('host')}:{rec.spec.get('port', 22)}"
        elif rec.type == "docker":
            extra = f" docker:{rec.spec.get('container')}"
            if rec.spec.get("user"):
                extra += f" as {rec.spec['user']}"
        desc = rec.spec.get("description") or ""
        if desc:
            extra += f" — {desc}"
        console.print(f"  - {rec.name} ({rec.type}){extra}")
    if not records:
        console.print("\n[dim]No SSH/Docker targets yet. Add with: ai-agent config execution-target add[/dim]")
    return 0


def cmd_add(
    console: Console,
    repo: UserExecutionTargetRepository,
    access,
    user_id: str,
    key_store: OSSecureKeyStore,
) -> int:
    record = access.get(user_id)
    if record is None or record.status != AccessStatus.APPROVED:
        console.print("[red]User is not approved on this deployment.[/red]")
        return 1
    linux = record.linux_username.strip()
    if not linux:
        console.print(
            "[red]User has no Linux account linked.[/red] "
            "Run: ai-agent config access approve <user_id> --run-as <linux_user>"
        )
        return 1

    console.print(
        "[bold]Add an execution target[/bold]\n"
        "The model will only see the name you choose — not host, key, or container details."
    )
    name = _prompt(console, "Target name (e.g. home-server)")
    try:
        from ai_agent.execution_targets.store import validate_target_name

        validate_target_name(name)
    except TargetConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    if name == RESERVED_LOCAL_NAME:
        console.print("[red]'local' is reserved for this machine.[/red]")
        return 1
    if repo.get_by_name(user_id, name) is not None:
        console.print(f"[red]Target {name!r} already exists.[/red]")
        return 1

    description = _prompt(console, "Short description", default="")
    kind = _prompt(console, "Type: ssh or docker").lower()
    if kind == "ssh":
        return _add_ssh(console, repo, access, user_id, name, description, linux, key_store)
    if kind == "docker":
        return _add_docker(console, repo, user_id, name, description)
    console.print("[red]Type must be ssh or docker.[/red]")
    return 1


def _add_ssh(
    console: Console,
    repo: UserExecutionTargetRepository,
    access,
    user_id: str,
    name: str,
    description: str,
    linux_username: str,
    key_store: OSSecureKeyStore,
) -> int:
    console.print(
        "\nSSH targets generate a [bold]new key for this target[/bold] under the "
        f"approved Linux user's home (~{linux_username}/.ai-agent/...)."
    )
    use_existing = confirm(
        console,
        "Reuse host / user / port from an existing Host in ~/.ssh/config",
    )
    host = ""
    user = ""
    port = 22
    if use_existing:
        imported = _import_host_details(console)
        if imported is None:
            return 1
        host, user, port = imported
    else:
        host = _prompt(console, "SSH hostname or IP")
        user = _prompt(console, "SSH user")
        port_text = _prompt(console, "SSH port", default="22")
        try:
            port = int(port_text)
        except ValueError:
            console.print("[red]Port must be a number.[/red]")
            return 1
    if not host or not user:
        console.print("[red]Host and user are required.[/red]")
        return 1

    rec = repo.add_ssh(
        user_id,
        name=name,
        host=host,
        user=user,
        port=port,
        description=description,
    )
    public = key_store.generate_ed25519_key_pair(linux_username, rec.id)
    console.print("\nInstall this public key on the remote machine (authorized_keys):")
    console.print(f"  {public}")

    known = key_store.get_known_hosts_path(linux_username, rec.id)
    if confirm(console, "Fetch and trust this host's SSH host key now"):
        _trust_ssh_host(console, host=host, port=port, user=user, known_hosts=known)

    console.print(f"\n[green]Saved[/green] SSH target {name!r} for this user.")
    return 0


def _add_docker(
    console: Console,
    repo: UserExecutionTargetRepository,
    user_id: str,
    name: str,
    description: str,
) -> int:
    container = _prompt(console, "Container name or ID (from `docker ps`)")
    if not container:
        console.print("[red]Container is required.[/red]")
        return 1
    console.print(
        "\nThe model cannot choose arbitrary containers — only this configured name."
    )
    user = _prompt(
        console,
        "Linux user inside the container (root = full control, empty = image USER)",
        default="root",
    )
    docker_bin = _prompt(console, "Docker binary", default="docker")
    repo.add_docker(
        user_id,
        name=name,
        container=container,
        description=description,
        docker_bin=docker_bin or "docker",
        user=user,
    )
    console.print(f"\n[green]Saved[/green] Docker target {name!r} for this user.")
    return 0


def _import_host_details(console: Console) -> tuple[str, str, int] | None:
    user_config = Path.home() / ".ssh" / "config"
    aliases = list_ssh_host_aliases(user_config)
    if not aliases:
        console.print(f"[red]No Host entries found in {user_config}[/red]")
        return None
    console.print("Existing SSH hosts:")
    for index, alias in enumerate(aliases, start=1):
        console.print(f"  {index}. {alias}")
    choice = _prompt(console, "Number or host name")
    alias = choice
    if choice.isdigit():
        number = int(choice)
        if number < 1 or number > len(aliases):
            console.print("[red]Invalid selection.[/red]")
            return None
        alias = aliases[number - 1]
    try:
        resolved = resolve_user_ssh_host(alias, user_config=user_config)
    except Exception as exc:
        console.print(f"[red]Could not resolve {alias!r}:[/red] {exc}")
        return None
    host = resolved.hostname or alias
    user = resolved.user or _prompt(console, "SSH user")
    return host, user, resolved.port


def _trust_ssh_host(
    console: Console,
    *,
    host: str,
    port: int,
    user: str,
    known_hosts: Path,
) -> bool:
    try:
        entries = scan_host_keys(host, port, user=user)
    except Exception as exc:
        console.print(f"[yellow]Could not scan host keys:[/yellow] {exc}")
        return False
    console.print("Host key(s) offered:")
    for line in entries:
        console.print(f"  {line}")
    if not confirm(console, "Trust these keys and save them for this target only"):
        return False
    append_known_hosts(known_hosts, entries)
    console.print(f"Saved to {known_hosts}")
    return True


def cmd_trust(
    console: Console,
    repo: UserExecutionTargetRepository,
    access,
    user_id: str,
    key_store: OSSecureKeyStore,
    name: str,
) -> int:
    record = access.get(user_id)
    if record is None or record.status != AccessStatus.APPROVED:
        console.print("[red]User is not approved.[/red]")
        return 1
    linux = record.linux_username.strip()
    if not linux:
        console.print("[red]User has no linked Linux account.[/red]")
        return 1
    rec = repo.get_ssh_by_name(user_id, name)
    if rec is None:
        console.print(f"[red]{name!r} is not an SSH target for this user.[/red]")
        return 1
    known = key_store.get_known_hosts_path(linux, rec.id)
    ok = _trust_ssh_host(
        console,
        host=str(rec.spec["host"]),
        port=int(rec.spec.get("port") or 22),
        user=str(rec.spec["user"]),
        known_hosts=known,
    )
    return 0 if ok else 1


def cmd_import_yaml(
    console: Console,
    *,
    path: Path,
    user_id: str,
    repo: UserExecutionTargetRepository,
    access,
) -> int:
    if not path.is_file():
        console.print(f"[red]No such file:[/red] {path}")
        return 1
    try:
        count = import_legacy_yaml(
            path,
            user_id=user_id,
            repo=repo,
            access_store=access,
        )
    except TargetConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(f"[green]Imported {count} target(s)[/green] into user {user_id}.")
    console.print(
        "[dim]Legacy YAML is not used at runtime. Remove or archive the file when done.[/dim]"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-agent config execution-target",
        description=(
            "Manage per-user SSH/Docker execution targets in the deployment database. "
            "See docs/execution-targets.md."
        ),
    )
    parser.add_argument(
        "--user-id",
        metavar="UUID",
        help="Supabase user id (default: ai-agent login session sub).",
    )
    parser.add_argument(
        "--service-db",
        action="store_true",
        help=(
            "Use the deployment database (CONVERSATION_DATABASE from .env, or "
            "/var/lib/ai-agent/conversations.db)."
        ),
    )
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list", help="List targets for the subject user.")
    sub.add_parser("add", help="Add an SSH or Docker target (wizard).")
    sub.add_parser("show", help="Same as list.")
    trust = sub.add_parser("trust", help="Trust SSH host keys for a target.")
    trust.add_argument("target_name", help="SSH target name.")
    imp = sub.add_parser(
        "import-yaml",
        help="One-time import from legacy global execution_targets.yaml.",
    )
    imp.add_argument(
        "path",
        nargs="?",
        default="execution_targets.yaml",
        help="Legacy YAML file (default: ./execution_targets.yaml).",
    )

    args = parser.parse_args(argv)
    console = Console()
    settings = Settings()
    action = args.action or "add"

    try:
        user_id = resolve_subject_user_id(settings, user_id_flag=args.user_id)
    except TargetSubjectError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    try:
        url, repo, access = _open_repo(settings, service_db=args.service_db)
    except (OSError, PermissionError) as exc:
        db_path = database_display_path(
            database_url_for_admin_cli(settings, service_db=args.service_db)
        )
        console.print(f"[red]Could not open database:[/red] {exc}")
        _print_shared_db_permission_hint(console, Path(db_path))
        return 1
    except Exception as exc:
        if _looks_like_sqlite_open_failure(exc):
            db_path = database_display_path(
                database_url_for_admin_cli(settings, service_db=args.service_db)
            )
            console.print(f"[red]Could not open database:[/red] {exc}")
            _print_shared_db_permission_hint(console, Path(db_path))
            return 1
        raise

    db_path = database_display_path(url)
    key_store = OSSecureKeyStore()

    if action in {"list", "show"}:
        return cmd_list(console, repo, user_id, db_path)
    if action == "add":
        return cmd_add(console, repo, access, user_id, key_store)
    if action == "trust":
        return cmd_trust(console, repo, access, user_id, key_store, args.target_name)
    if action == "import-yaml":
        return cmd_import_yaml(
            console,
            path=Path(args.path),
            user_id=user_id,
            repo=repo,
            access=access,
        )
    parser.print_help()
    return 1
