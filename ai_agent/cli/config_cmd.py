from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ai_agent.config import Settings
from ai_agent.cli.confirm import confirm
from ai_agent.llm.ssh_sandbox import (
    ResolvedSshHost,
    append_known_hosts,
    copy_identity_into_sandbox,
    default_sandbox_dir,
    disable_remote_provider_env,
    generate_ed25519_key,
    host_setup_next_steps,
    is_host_key_failure,
    list_ssh_host_aliases,
    read_public_key,
    remote_provider_env_values,
    resolve_user_ssh_host,
    scan_host_keys,
    upsert_env_values,
    write_sandbox_host_config,
)
from ai_agent.llm.ssh_tunnel import require_ssh_binary, start_ssh_tunnel

COPY_WARNING = (
    "This will copy SSH files into this project's sandbox (.ai-agent/ssh/). "
    "The agent will not use ~/.ssh at runtime after that. "
    "Private keys are secrets: you will have a second copy on disk."
)


def _prompt(console: Console, label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = console.input(f"{label}{suffix}: ").strip()
    return value or default


def cmd_show(console: Console, settings: Settings) -> int:
    console.print("[bold]Current LLM transport[/bold]")
    console.print(f"  OLLAMA_TRANSPORT = {settings.ollama_transport.value}")
    console.print(f"  OLLAMA_HOST      = {settings.ollama_host}")
    console.print(f"  OLLAMA_UPSTREAM  = {settings.ollama_upstream}")
    if settings.ollama_transport.value == "ssh":
        console.print(f"  OLLAMA_SSH_HOST  = {settings.ollama_ssh_host or '(empty)'}")
        console.print(f"  OLLAMA_SSH_CONFIG= {settings.ollama_ssh_config}")
        console.print(f"  OLLAMA_SSH_REMOTE= {settings.ollama_ssh_remote}")
    return 0


def cmd_disable(console: Console, env_path: Path) -> int:
    disable_remote_provider_env(env_path)
    console.print(f"Wrote {env_path} with OLLAMA_TRANSPORT=http (local Ollama).")
    return 0


def _trust_host_key(console: Console, settings: Settings) -> bool:
    """Fetch the GPU host key into the sandbox known_hosts after confirmation."""
    try:
        resolved = resolve_user_ssh_host(
            settings.ollama_ssh_host.strip(),
            user_config=settings.ollama_ssh_config,
        )
    except Exception as exc:
        console.print(f"[red]Could not read sandbox SSH config:[/red] {exc}")
        return False
    console.print(
        f"Fetching SSH host key for [bold]{resolved.hostname}:{resolved.port}[/bold] "
        "(this is the GPU PC's sshd key, not Ollama)."
    )
    try:
        entries = scan_host_keys(resolved.hostname, resolved.port)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        return False
    console.print("Host key(s) offered by that machine:")
    for line in entries:
        console.print(f"  {line}")
    if not confirm(console, "Trust these keys and save them in .ai-agent/ssh/known_hosts"):
        return False
    known_hosts = settings.ollama_ssh_config.parent / "known_hosts"
    append_known_hosts(known_hosts, entries)
    console.print(f"Saved {len(entries)} key(s) to {known_hosts}")
    return True


def cmd_test(console: Console, settings: Settings, *, _retried: bool = False) -> int:
    if settings.ollama_transport.value != "ssh":
        console.print("[yellow]OLLAMA_TRANSPORT is not ssh. Nothing to test.[/yellow]")
        return 1
    try:
        require_ssh_binary()
        tunnel = start_ssh_tunnel(settings)
    except Exception as exc:
        console.print(f"[red]SSH tunnel failed:[/red] {exc}")
        if is_host_key_failure(str(exc)) and not _retried:
            console.print(
                "\nThe sandbox [bold]known_hosts[/bold] file does not trust this PC yet. "
                "That is expected the first time. It is not an Ollama or ai-agent-llm problem."
            )
            if confirm(console, "Fetch and trust the SSH host key now"):
                if _trust_host_key(console, settings):
                    return cmd_test(console, settings, _retried=True)
        return 1
    try:
        from ai_agent.llm.factory import create_llm_provider
        from ai_agent.llm.session import LlmHttpSession

        session = LlmHttpSession(
            tunnel.local_url,
            timeout=10.0,
            before_request=tunnel.ensure,
        )
        provider = create_llm_provider(settings, session=session)
        health = provider.healthcheck()
        provider.close()
        if not health.ok:
            console.print(f"[red]Tunnel is up, but Ollama failed:[/red] {health.message}")
            return 1
        console.print(f"[green]SSH tunnel and Ollama healthcheck ok[/green] ({tunnel.local_url})")
        return 0
    finally:
        tunnel.close()


def _import_host(console: Console, sandbox: Path, user_config: Path) -> tuple | None:
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
    resolved = resolve_user_ssh_host(alias, user_config=user_config)
    if not resolved.user:
        resolved_user = _prompt(console, "SSH user", default="")
    else:
        resolved_user = resolved.user
    identity = next((path for path in resolved.identity_files if path.is_file()), None)
    if identity is None:
        console.print("[red]Could not find an IdentityFile for that host to copy.[/red]")
        return None
    dest = copy_identity_into_sandbox(identity, sandbox, stem=f"id_{resolved.alias}")
    host = ResolvedSshHost(
        alias=resolved.alias,
        hostname=resolved.hostname,
        user=resolved_user,
        port=resolved.port,
        identity_files=[dest],
    )
    return host, dest


def cmd_remote_provider(
    console: Console,
    *,
    read_existing: bool,
    env_path: Path,
    sandbox: Path,
    user_ssh_config: Path,
) -> int:
    try:
        require_ssh_binary()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    console.print(Panel(COPY_WARNING, title="SSH sandbox", border_style="yellow"))
    if not confirm(console, "Continue"):
        console.print("Cancelled.")
        return 1

    sandbox.mkdir(parents=True, exist_ok=True)
    identity: Path
    if read_existing:
        imported = _import_host(console, sandbox, user_ssh_config)
        if imported is None:
            return 1
        host, identity = imported
    else:
        alias = _prompt(console, "SSH host alias (name in our sandbox config)", "gpu-box")
        hostname = _prompt(console, "Hostname or IP")
        if not hostname:
            console.print("[red]Hostname is required.[/red]")
            return 1
        user = _prompt(console, "SSH user")
        if not user:
            console.print("[red]SSH user is required.[/red]")
            return 1
        port_text = _prompt(console, "SSH port", "22")
        host = ResolvedSshHost(
            alias=alias,
            hostname=hostname,
            user=user,
            port=int(port_text or "22"),
            identity_files=[],
        )
        passphrase = _prompt(
            console,
            "Key passphrase (empty = none; empty is easier and weaker)",
            "",
        )
        identity = generate_ed25519_key(sandbox / "id_ed25519", passphrase=passphrase)

    write_sandbox_host_config(sandbox, host, identity)
    if confirm(console, "Fetch and trust the GPU PC's SSH host key now"):
        settings_preview = Settings()
        settings_preview.ollama_ssh_config = sandbox / "config"
        settings_preview.ollama_ssh_host = host.alias
        _trust_host_key(console, settings_preview)
    public_key = read_public_key(identity)
    gpu_os = _prompt(console, "GPU machine OS (windows/linux)", "windows").lower()
    if gpu_os not in {"windows", "linux"}:
        gpu_os = "windows"
    remote = _prompt(console, "Ollama on the GPU box", "127.0.0.1:11434")

    key_file = sandbox / "host-setup.pub"
    key_file.write_text(public_key + "\n", encoding="utf-8")
    console.print()
    console.print(host_setup_next_steps(key_file=key_file, linux=gpu_os == "linux"))
    console.print(f"Sandbox config: {sandbox / 'config'}")
    console.print(f"Copied/generated key: {identity}")

    values = remote_provider_env_values(
        alias=host.alias,
        config_path=sandbox / "config",
        remote=remote or "127.0.0.1:11434",
    )
    console.print("\n[bold]Copy into .env (or allow the wizard to write it):[/bold]")
    for key, value in values.items():
        console.print(f"  {key}={value}")

    if confirm(console, f"Write these values to {env_path}"):
        upsert_env_values(env_path, values)
        console.print(f"Updated {env_path}")

    console.print(
        "\nAfter host-setup succeeds on the GPU PC, run:\n"
        "  ai-agent config remote-provider test"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-agent config",
        description="Configure this project without starting the agent REPL.",
    )
    sub = parser.add_subparsers(dest="command")
    remote = sub.add_parser(
        "remote-provider",
        help="Set up a sandboxed SSH tunnel to a remote Ollama host.",
    )
    remote.add_argument(
        "--read-existing-ssh-hosts",
        action="store_true",
        help="Import a Host from ~/.ssh/config and copy its key into the sandbox.",
    )
    remote.add_argument(
        "action",
        nargs="?",
        choices=["test", "disable", "trust-host"],
        help="test the tunnel, switch .env back to local HTTP, or trust the SSH host key.",
    )
    sub.add_parser("show", help="Print the current LLM transport settings.")

    args = parser.parse_args(argv)
    console = Console()
    settings = Settings()
    env_path = Path(".env")
    sandbox = default_sandbox_dir()
    user_config = Path.home() / ".ssh" / "config"

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "show":
        return cmd_show(console, settings)
    if args.command == "remote-provider":
        if args.action == "test":
            return cmd_test(console, settings)
        if args.action == "trust-host":
            return 0 if _trust_host_key(console, settings) else 1
        if args.action == "disable":
            return cmd_disable(console, env_path)
        return cmd_remote_provider(
            console,
            read_existing=args.read_existing_ssh_hosts,
            env_path=env_path,
            sandbox=sandbox,
            user_ssh_config=user_config,
        )
    parser.print_help()
    return 0
