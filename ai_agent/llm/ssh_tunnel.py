from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from ai_agent.config import Settings
from ai_agent.llm.base import LLMErrorKind
from ai_agent.llm.session import LlmSessionError
from ai_agent.llm.ssh_sandbox import ssh_path_for_config

logger = logging.getLogger(__name__)


def parse_remote_bind(value: str) -> tuple[str, int]:
    if ":" not in value:
        raise ValueError(f"OLLAMA_SSH_REMOTE must look like 127.0.0.1:11434, got {value!r}")
    host, port_text = value.rsplit(":", 1)
    return host, int(port_text)


def pick_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(port: int, *, timeout: float = 15.0, process: subprocess.Popen | None = None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            stderr = ""
            if process.stderr is not None:
                stderr = process.stderr.read()
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
            raise LlmSessionError(
                LLMErrorKind.UNAVAILABLE,
                f"SSH tunnel exited before it was ready. {stderr.strip()}".strip(),
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.15)
    raise LlmSessionError(
        LLMErrorKind.TIMEOUT,
        f"SSH tunnel did not open 127.0.0.1:{port} in time.",
    )


class SshTunnel:
    def __init__(
        self,
        process: subprocess.Popen,
        local_port: int,
        remote: str,
    ):
        self.process = process
        self.local_port = local_port
        self.remote = remote

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.local_port}"

    def alive(self) -> bool:
        return self.process.poll() is None

    def ensure(self) -> None:
        if not self.alive():
            raise LlmSessionError(
                LLMErrorKind.SESSION_CLOSED,
                "SSH tunnel is gone.",
            )

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)


def build_ssh_forward_command(
    settings: Settings,
    *,
    local_port: int,
    ssh_bin: str,
) -> list[str]:
    remote_host, remote_port = parse_remote_bind(settings.ollama_ssh_remote)
    config = settings.ollama_ssh_config
    if not config.is_file():
        raise LlmSessionError(
            LLMErrorKind.UNAVAILABLE,
            f"SSH config not found: {config}. Run: ai-agent config remote-provider",
        )
    if not settings.ollama_ssh_host.strip():
        raise LlmSessionError(
            LLMErrorKind.UNAVAILABLE,
            "OLLAMA_SSH_HOST is empty. Run: ai-agent config remote-provider",
        )
    known_hosts = config.parent / "known_hosts"
    return [
        ssh_bin,
        "-N",
        "-F",
        str(config),
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        f"UserKnownHostsFile={ssh_path_for_config(known_hosts)}",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-L",
        f"127.0.0.1:{local_port}:{remote_host}:{remote_port}",
        settings.ollama_ssh_host.strip(),
    ]


def start_ssh_tunnel(
    settings: Settings,
    *,
    ssh_bin: str | None = None,
    wait_timeout: float = 15.0,
) -> SshTunnel:
    binary = ssh_bin or shutil.which("ssh")
    if not binary:
        raise LlmSessionError(
            LLMErrorKind.UNAVAILABLE,
            "ssh was not found on PATH. Install OpenSSH Client.",
        )
    local_port = settings.ollama_ssh_local_port or pick_local_port()
    command = build_ssh_forward_command(settings, local_port=local_port, ssh_bin=binary)
    logger.info("Starting SSH tunnel to %s via %s", settings.ollama_ssh_remote, settings.ollama_ssh_host)
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    try:
        wait_for_port(local_port, timeout=wait_timeout, process=process)
    except Exception:
        if process.poll() is None:
            process.kill()
        raise
    return SshTunnel(process, local_port, settings.ollama_ssh_remote)


def require_ssh_binary() -> str:
    path = shutil.which("ssh")
    if not path:
        raise FileNotFoundError("ssh was not found on PATH. Install OpenSSH Client.")
    return path
