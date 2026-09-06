from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ai_agent.cli.confirm import confirm
from ai_agent.config import Settings
from ai_agent.execution_targets.store import (
    DockerTargetRecord,
    RESERVED_LOCAL_NAME,
    SshTargetRecord,
    TargetConfigError,
    execution_target_dir,
    load_targets_file,
    upsert_target,
    validate_target_name,
)
from ai_agent.llm.ssh_sandbox import (
    append_known_hosts,
    generate_ed25519_key,
    list_ssh_host_aliases,
    read_public_key,
    resolve_user_ssh_host,
    scan_host_keys,
)


def _prompt(console: Console, label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = console.input(f"{label}{suffix}: ").strip()
    return value or default


def cmd_list(console: Console, settings: Settings) -> int:
    path = settings.agent_execution_targets_file
    document = load_targets_file(path)
    console.print(f"[bold]Execution targets[/bold] ({path})")
    console.print(f"  Default: {document.default_target}")
    for name, record in document.execution_targets.items():
        extra = ""
        if record.type == "ssh":
            extra = f" ssh://{record.user}@{record.host}:{record.port}"
        elif record.type == "docker":
            extra = f" docker:{record.container}"
        desc = f" — {record.description}" if record.description else ""
        console.print(f"  - {name} ({record.type}){extra}{desc}")
    if not path.is_file():
        console.print(
            "\n[dim]No file yet. Only the built-in local target is active. "
            "Add more with: ai-agent config execution-target[/dim]"
        )
    return 0


def cmd_add(console: Console, settings: Settings) -> int:
    path = settings.agent_execution_targets_file
    document = load_targets_file(path)
    console.print(
        "[bold]Add an execution target[/bold]\n"
        "The model will only see the name you choose — not host, key, or container details."
    )
    name = _prompt(console, "Target name (e.g. home-server)")
    try:
        validate_target_name(name)
    except TargetConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    if name in document.execution_targets:
        console.print(f"[red]Target {name!r} already exists.[/red]")
        return 1
    if name == RESERVED_LOCAL_NAME:
        console.print("[red]'local' is reserved for this machine.[/red]")
        return 1

    description = _prompt(console, "Short description", default="")
    kind = _prompt(console, "Type: ssh or docker").lower()
    if kind == "ssh":
        record = _wizard_ssh(console, name, description)
    elif kind == "docker":
        record = _wizard_docker(console, description)
    else:
        console.print("[red]Type must be ssh or docker. local is always present.[/red]")
        return 1
    if record is None:
        return 1
    upsert_target(path, name, record)
    console.print(f"\n[green]Saved[/green] target {name!r} to {path}")
    console.print(
        "The agent loads this file at startup. Restart ai-agent to use the new target."
    )
    return 0


def _wizard_ssh(console: Console, name: str, description: str) -> SshTargetRecord | None:
    console.print(
        "\nSSH targets generate a [bold]new key just for this target[/bold]. "
        "Your existing ~/.ssh keys stay yours."
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
            return None
        host, user, port = imported
        console.print(
            f"Using {user}@{host}:{port}. A new agent key will be generated "
            "(your existing identity is not copied)."
        )
    else:
        host = _prompt(console, "SSH hostname or IP")
        user = _prompt(console, "SSH user")
        port_text = _prompt(console, "SSH port", default="22")
        try:
            port = int(port_text)
        except ValueError:
            console.print("[red]Port must be a number.[/red]")
            return None
    if not host or not user:
        console.print("[red]Host and user are required.[/red]")
        return None

    target_dir = execution_target_dir(name)
    identity = generate_ed25519_key(
        target_dir / "id_ed25519",
        comment=f"ai-agent-exec-{name}",
    )
    known_hosts = target_dir / "known_hosts"
    if not known_hosts.exists():
        known_hosts.touch()
    public_key = read_public_key(identity)
    key_file = target_dir / "host-setup.pub"
    key_file.write_text(public_key + "\n", encoding="utf-8")

    console.print(f"\nGenerated key: {identity}")
    console.print("Install this public key on the remote machine (authorized_keys):")
    console.print(f"  {public_key}")
    console.print(f"Copied to {key_file} for convenience.")

    if confirm(console, "Fetch and trust this host's SSH host key now"):
        _trust_ssh_host(console, host=host, port=port, user=user, known_hosts=known_hosts)

    return SshTargetRecord(
        type="ssh",
        description=description,
        host=host,
        user=user,
        port=port,
        identity_file=identity,
        known_hosts=known_hosts,
    )


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


def cmd_trust(console: Console, settings: Settings, name: str = "") -> int:
    document = load_targets_file(settings.agent_execution_targets_file)
    ssh_names = [
        item
        for item, record in document.execution_targets.items()
        if isinstance(record, SshTargetRecord)
    ]
    if not ssh_names:
        console.print("[red]No SSH execution targets are configured.[/red]")
        return 1
    if not name:
        console.print("SSH targets:")
        for index, item in enumerate(ssh_names, start=1):
            console.print(f"  {index}. {item}")
        name = _prompt(console, "Target to trust")
        if name.isdigit():
            number = int(name)
            if 1 <= number <= len(ssh_names):
                name = ssh_names[number - 1]
    record = document.execution_targets.get(name)
    if not isinstance(record, SshTargetRecord):
        console.print(f"[red]{name!r} is not an SSH execution target.[/red]")
        return 1
    known = record.known_hosts or execution_target_dir(name) / "known_hosts"
    ok = _trust_ssh_host(
        console,
        host=record.host,
        port=record.port,
        user=record.user,
        known_hosts=known,
    )
    return 0 if ok else 1


def _wizard_docker(console: Console, description: str) -> DockerTargetRecord | None:
    container = _prompt(console, "Container name or ID (from `docker ps`)")
    if not container:
        console.print("[red]Container is required.[/red]")
        return None
    docker_bin = _prompt(console, "Docker binary", default="docker")
    return DockerTargetRecord(
        type="docker",
        description=description,
        container=container,
        docker_bin=docker_bin or "docker",
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    console = Console()
    settings = Settings()
    if not args or args[0] in {"add", "wizard"}:
        return cmd_add(console, settings)
    if args[0] in {"list", "show"}:
        return cmd_list(console, settings)
    if args[0] == "trust":
        target_name = args[1] if len(args) > 1 else ""
        return cmd_trust(console, settings, target_name)
    console.print("Usage: ai-agent config execution-target [add|list|trust]")
    return 1
