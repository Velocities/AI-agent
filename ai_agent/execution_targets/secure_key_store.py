from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path
from typing import Protocol

from ai_agent.commands.run_as import lookup_posix_account

TARGET_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def validate_target_id(target_id: str) -> str:
    cleaned = target_id.strip().lower()
    if not TARGET_ID_RE.match(cleaned):
        raise ValueError(f"Invalid target id {target_id!r}")
    return cleaned


class SecureKeyStore(Protocol):
    """Secure storage and retrieval of SSH key material."""

    def initialize_target(self, linux_username: str, target_id: str) -> None: ...

    def get_identity_private_path(self, linux_username: str, target_id: str) -> Path: ...

    def get_identity_public_key(self, linux_username: str, target_id: str) -> str: ...

    def get_known_hosts_path(self, linux_username: str, target_id: str) -> Path: ...

    def generate_ed25519_key_pair(self, linux_username: str, target_id: str) -> str: ...


class OSSecureKeyStore:
    """Store SSH keys under the approved Linux user's home directory."""

    def __init__(self, *, app_dir_name: str = ".ai-agent") -> None:
        self._app_dir_name = app_dir_name

    def _target_root(self, linux_username: str, target_id: str) -> Path:
        tid = validate_target_id(target_id)
        account = lookup_posix_account(linux_username)
        root = Path(account.home) / self._app_dir_name / "execution-targets" / tid
        root = root.resolve()
        allowed = (Path(account.home) / self._app_dir_name / "execution-targets").resolve()
        if not str(root).startswith(str(allowed) + "/") and root != allowed:
            raise ValueError("target path escapes managed root")
        return root

    def initialize_target(self, linux_username: str, target_id: str) -> None:
        root = self._target_root(linux_username, target_id)
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(stat.S_IRWXU)
        account = lookup_posix_account(linux_username)
        try:
            import os

            os.chown(root, account.uid, account.gid)
        except (AttributeError, PermissionError):
            pass
        known = root / "known_hosts"
        if not known.exists():
            known.write_text("", encoding="utf-8")
            known.chmod(stat.S_IRUSR | stat.S_IWUSR)
            try:
                import os

                os.chown(known, account.uid, account.gid)
            except (AttributeError, PermissionError):
                pass

    def get_identity_private_path(self, linux_username: str, target_id: str) -> Path:
        path = self._target_root(linux_username, target_id) / "id_ed25519"
        if not path.is_file():
            raise FileNotFoundError(f"SSH private key missing for target {target_id}")
        return path

    def get_identity_public_key(self, linux_username: str, target_id: str) -> str:
        pub = self._target_root(linux_username, target_id) / "id_ed25519.pub"
        if not pub.is_file():
            raise FileNotFoundError(f"SSH public key missing for target {target_id}")
        line = pub.read_text(encoding="utf-8").strip().splitlines()
        return line[0] if line else ""

    def get_known_hosts_path(self, linux_username: str, target_id: str) -> Path:
        return self._target_root(linux_username, target_id) / "known_hosts"

    def generate_ed25519_key_pair(self, linux_username: str, target_id: str) -> str:
        self.initialize_target(linux_username, target_id)
        root = self._target_root(linux_username, target_id)
        private = root / "id_ed25519"
        public = root / "id_ed25519.pub"
        if private.exists():
            private.unlink()
        if public.exists():
            public.unlink()
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-f",
                str(private),
                "-N",
                "",
                "-C",
                f"ai-agent-exec-{target_id}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        private.chmod(stat.S_IRUSR)
        public.chmod(stat.S_IRUSR | stat.S_IWUSR)
        account = lookup_posix_account(linux_username)
        try:
            import os

            os.chown(private, account.uid, account.gid)
            os.chown(public, account.uid, account.gid)
        except (AttributeError, PermissionError):
            pass
        return self.get_identity_public_key(linux_username, target_id)
