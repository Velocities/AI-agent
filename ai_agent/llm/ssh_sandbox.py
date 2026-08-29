from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_HOST_LINE = re.compile(r"^Host\s+(.+)$", re.IGNORECASE)
_G_LINE = re.compile(r"^(\S+)\s+(.*)$")


@dataclass(frozen=True)
class ResolvedSshHost:
    alias: str
    hostname: str
    user: str
    port: int
    identity_files: list[Path]


def default_sandbox_dir(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / ".ai-agent" / "ssh"


def ssh_path_for_config(path: Path) -> str:
    """OpenSSH on Windows accepts forward slashes in config files."""
    return path.resolve().as_posix()


def list_ssh_host_aliases(config_path: Path) -> list[str]:
    if not config_path.is_file():
        return []
    aliases: list[str] = []
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        match = _HOST_LINE.match(line)
        if not match:
            continue
        for name in match.group(1).split():
            if name == "*" or "*" in name:
                continue
            if name not in aliases:
                aliases.append(name)
    return aliases


def parse_ssh_g(output: str, *, alias: str) -> ResolvedSshHost:
    values: dict[str, list[str]] = {}
    for raw in output.splitlines():
        match = _G_LINE.match(raw.strip())
        if not match:
            continue
        key, value = match.group(1).lower(), match.group(2).strip()
        values.setdefault(key, []).append(value)

    def first(name: str, default: str = "") -> str:
        items = values.get(name)
        return items[0] if items else default

    identities: list[Path] = []
    for item in values.get("identityfile", []):
        path = Path(item).expanduser()
        if path not in identities:
            identities.append(path)

    port_text = first("port", "22")
    try:
        port = int(port_text)
    except ValueError:
        port = 22

    return ResolvedSshHost(
        alias=alias,
        hostname=first("hostname", alias),
        user=first("user"),
        port=port,
        identity_files=identities,
    )


def resolve_user_ssh_host(
    alias: str,
    *,
    user_config: Path,
    ssh_bin: str = "ssh",
) -> ResolvedSshHost:
    result = subprocess.run(
        [ssh_bin, "-G", "-F", str(user_config), alias],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_ssh_g(result.stdout, alias=alias)


def copy_identity_into_sandbox(source: Path, sandbox: Path, *, stem: str) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Identity file not found: {source}")
    sandbox.mkdir(parents=True, exist_ok=True)
    dest = sandbox / stem
    shutil.copy2(source, dest)
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    pub = source.with_name(source.name + ".pub")
    if not pub.is_file() and source.suffix == "":
        pub = Path(str(source) + ".pub")
    if pub.is_file():
        shutil.copy2(pub, Path(str(dest) + ".pub"))
    return dest


def write_sandbox_host_config(
    sandbox: Path,
    host: ResolvedSshHost,
    identity_file: Path,
) -> Path:
    sandbox.mkdir(parents=True, exist_ok=True)
    config_path = sandbox / "config"
    known_hosts = sandbox / "known_hosts"
    if not known_hosts.exists():
        known_hosts.touch()
    body = (
        f"Host {host.alias}\n"
        f"    HostName {host.hostname}\n"
        f"    User {host.user}\n"
        f"    Port {host.port}\n"
        f"    IdentityFile {ssh_path_for_config(identity_file)}\n"
        f"    IdentitiesOnly yes\n"
        f"    UserKnownHostsFile {ssh_path_for_config(known_hosts)}\n"
        f"    StrictHostKeyChecking yes\n"
    )
    config_path.write_text(body, encoding="utf-8")
    return config_path


def generate_ed25519_key(
    dest: Path,
    *,
    comment: str = "ai-agent-llm",
    passphrase: str = "",
    ssh_keygen: str = "ssh-keygen",
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    pub = Path(str(dest) + ".pub")
    if pub.exists():
        pub.unlink()
    subprocess.run(
        [
            ssh_keygen,
            "-t",
            "ed25519",
            "-f",
            str(dest),
            "-N",
            passphrase,
            "-C",
            comment,
            "-q",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    return dest


def read_public_key(identity_file: Path) -> str:
    pub = Path(str(identity_file) + ".pub")
    if not pub.is_file():
        raise FileNotFoundError(f"Public key not found: {pub}")
    return pub.read_text(encoding="utf-8").strip()


def gpu_setup_instructions(*, gpu_os: str, public_key: str) -> str:
    if gpu_os == "windows":
        return (
            "On the Windows GPU PC (OpenSSH Server must be running):\n\n"
            "1. Keep Ollama listening on 127.0.0.1:11434 only. Do not expose 11434.\n"
            "2. If this account is a normal user, append this line to\n"
            "   C:\\Users\\<you>\\.ssh\\authorized_keys\n"
            "   If the account is in Administrators, Windows often requires\n"
            "   C:\\ProgramData\\ssh\\administrators_authorized_keys instead.\n\n"
            f"   {public_key}\n\n"
            "3. The key must be one single line. Do not wrap it.\n"
            "4. If this account is in Administrators, the user authorized_keys\n"
            "   file is ignored. Use administrators_authorized_keys, then:\n"
            "   icacls C:\\ProgramData\\ssh\\administrators_authorized_keys /inheritance:r\n"
            "   icacls C:\\ProgramData\\ssh\\administrators_authorized_keys "
            "/grant SYSTEM:(F) \"BUILTIN\\Administrators:(F)\"\n"
            "   Restart-Service sshd\n"
            "5. Allow inbound TCP 22 (or only on your VPN/Tailscale interface).\n"
        )
    return (
        "On the Linux GPU machine:\n\n"
        "1. Keep Ollama listening on 127.0.0.1:11434 only. Do not expose 11434.\n"
        "2. Append this line to ~/.ssh/authorized_keys:\n\n"
        f"   {public_key}\n\n"
        "3. Then:\n"
        "   mkdir -p ~/.ssh && chmod 700 ~/.ssh\n"
        "   chmod 600 ~/.ssh/authorized_keys\n"
    )


def upsert_env_values(env_path: Path, values: dict[str, str]) -> None:
    """Replace or append selected keys, leaving other lines intact."""
    existing: list[str] = []
    if env_path.is_file():
        existing = env_path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    rewritten: list[str] = []
    for line in existing:
        stripped = line.strip()
        key = stripped.split("=", 1)[0] if "=" in stripped and not stripped.startswith("#") else ""
        if key in values:
            rewritten.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            rewritten.append(line)
    for key, value in values.items():
        if key not in seen:
            rewritten.append(f"{key}={value}")
    env_path.write_text("\n".join(rewritten).rstrip() + "\n", encoding="utf-8")


def remote_provider_env_values(
    *,
    alias: str,
    config_path: Path,
    remote: str = "127.0.0.1:11434",
) -> dict[str, str]:
    return {
        "OLLAMA_TRANSPORT": "ssh",
        "OLLAMA_HOST": "http://127.0.0.1:11434",
        "OLLAMA_UPSTREAM": "http://127.0.0.1:11434",
        "OLLAMA_SSH_HOST": alias,
        "OLLAMA_SSH_CONFIG": str(config_path).replace("\\", "/"),
        "OLLAMA_SSH_REMOTE": remote,
    }


def is_auth_failure(message: str) -> bool:
    lowered = message.lower()
    return "permission denied" in lowered and (
        "publickey" in lowered or "authentication" in lowered or "keyboard-interactive" in lowered
    )


def sandbox_identity_file(settings) -> Path:
    """Private key from our sandbox only — not ~/.ssh defaults from `ssh -G`."""
    sandbox = Path(settings.ollama_ssh_config).expanduser().resolve().parent
    config = sandbox / "config"
    if config.is_file():
        for raw in config.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line.lower().startswith("identityfile "):
                continue
            path = Path(line.split(None, 1)[1].strip().strip('"')).expanduser()
            if path.is_file():
                return path
    privates = [
        path
        for path in sandbox.iterdir()
        if path.is_file()
        and path.name.startswith("id_")
        and not path.name.endswith(".pub")
    ]
    if not privates:
        raise FileNotFoundError(
            f"No sandbox private key in {sandbox}. Run: ai-agent config remote-provider"
        )
    return privates[0]


def sandbox_public_key_text(settings) -> str:
    identity = sandbox_identity_file(settings)
    pub = Path(str(identity) + ".pub")
    if not pub.is_file():
        raise FileNotFoundError(f"Public key not found: {pub}")
    return pub.read_text(encoding="utf-8").strip()


def is_host_key_failure(message: str) -> bool:
    lowered = message.lower()
    return (
        "host key verification failed" in lowered
        or "no ed25519 host key is known" in lowered
        or "no ecdsa host key is known" in lowered
        or "no rsa host key is known" in lowered
        or "not known and you have requested strict checking" in lowered
    )


def parse_keyscan_lines(output: str) -> list[str]:
    lines: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def scan_host_keys(
    hostname: str,
    port: int = 22,
    *,
    ssh_keyscan: str = "ssh-keyscan",
) -> list[str]:
    result = subprocess.run(
        [ssh_keyscan, "-T", "5", "-p", str(port), hostname],
        check=False,
        capture_output=True,
        text=True,
    )
    lines = parse_keyscan_lines(result.stdout)
    if not lines:
        detail = (result.stderr or result.stdout or "no keys returned").strip()
        raise RuntimeError(f"ssh-keyscan failed for {hostname}:{port}. {detail}")
    return lines


def append_known_hosts(known_hosts: Path, entries: list[str]) -> None:
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if known_hosts.is_file():
        existing = known_hosts.read_text(encoding="utf-8")
    new_lines = [line for line in entries if line not in existing]
    if not new_lines:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with known_hosts.open("a", encoding="utf-8") as handle:
        handle.write(prefix + "\n".join(new_lines) + "\n")


def disable_remote_provider_env(env_path: Path) -> None:
    upsert_env_values(
        env_path,
        {
            "OLLAMA_TRANSPORT": "http",
            "OLLAMA_HOST": "http://localhost:11434",
            "OLLAMA_UPSTREAM": "http://localhost:11434",
        },
    )
