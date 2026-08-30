from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path


def normalize_public_key(raw: str) -> str:
    line = " ".join(raw.strip().split())
    if not line.startswith(("ssh-", "ecdsa-", "sk-")):
        raise ValueError("That does not look like an OpenSSH public key line.")
    return line


def merge_authorized_key(path: Path, public_key: str) -> bool:
    """Append public_key if missing. Return True when a line was added."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    keys = {line.strip() for line in existing.splitlines() if line.strip()}
    if public_key in keys:
        return False
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{prefix}{public_key}\n")
    return True


def windows_authorized_keys_path(*, home: Path, admin_account: bool) -> Path:
    if admin_account:
        return Path(r"C:\ProgramData\ssh\administrators_authorized_keys")
    return home / ".ssh" / "authorized_keys"


def linux_authorized_keys_path(home: Path) -> Path:
    return home / ".ssh" / "authorized_keys"


def ollama_is_listening(host: str = "127.0.0.1", port: int = 11434) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def windows_account_is_elevated() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def restrict_windows_admin_key_acl(path: Path) -> None:
    subprocess.run(
        ["icacls", str(path), "/inheritance:r"],
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "icacls",
            str(path),
            "/grant",
            "SYSTEM:(F)",
            "BUILTIN\\Administrators:(F)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def restart_sshd() -> tuple[bool, str]:
    if sys.platform == "win32":
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Restart-Service sshd"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, "Restarted sshd."
        return False, (result.stderr or result.stdout or "Restart-Service sshd failed.").strip()
    for command in (
        ["systemctl", "restart", "ssh"],
        ["systemctl", "restart", "sshd"],
        ["service", "ssh", "restart"],
    ):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return True, f"Restarted via {' '.join(command)}."
    return False, "Could not restart sshd. Start the OpenSSH Server service yourself."
