"""Start ai-agent serve in local standalone mode and open a terminal chat session."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from rich.console import Console

from ai_agent_cli.auth.local import LocalStandaloneAuth
from ai_agent_cli.client_state import ServerConfig
from ai_agent_cli.contracts import DEFAULT_LOCAL_STANDALONE_USER_ID
from ai_agent_cli.terminal_chat import run_terminal_chat

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class LocalServerProcess:
    process: subprocess.Popen[bytes]
    base_url: str
    token: str


def _pick_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_local_server(console: Console) -> LocalServerProcess | None:
    token = secrets.token_urlsafe(32)
    port = _pick_loopback_port()
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"
    env = os.environ.copy()
    env["LOCAL_STANDALONE_MODE"] = "1"
    env["LOCAL_STANDALONE_TOKEN"] = token
    env.setdefault("LOCAL_STANDALONE_USER_ID", DEFAULT_LOCAL_STANDALONE_USER_ID)
    env["API_BIND_HOST"] = host
    env["API_BIND_PORT"] = str(port)
    command = [sys.executable, "-m", "ai_agent.service.supervisor"]
    console.print(
        f"[dim]Starting local agent server on {base_url} (ai-agent serve)…[/dim]"
    )
    try:
        process = subprocess.Popen(
            command,
            env=env,
            cwd=_REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        console.print(f"[red]Could not start the local server:[/red] {exc}")
        return None
    if not _wait_for_ready(base_url, token, process):
        console.print(
            "[red]Local server did not accept the standalone bearer token.[/red]"
        )
        console.print(
            "[dim]If another ai-agent serve is already running, stop it or use "
            "ai-agent-chat with a saved server URL.[/dim]"
        )
        try:
            process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        if process.stderr:
            detail = process.stderr.read().decode("utf-8", errors="replace").strip()
            if detail:
                console.print(f"[dim]{detail[-3000:]}[/dim]")
        return None
    return LocalServerProcess(process=process, base_url=base_url, token=token)


def _wait_for_ready(
    base_url: str,
    token: str,
    process: subprocess.Popen[bytes],
    *,
    timeout: float = 300.0,
) -> bool:
    """Wait until /health is up and /api/me accepts our standalone bearer."""
    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    origin = base_url.rstrip("/")
    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            try:
                health = client.get(f"{origin}/health")
                if health.status_code != 200:
                    time.sleep(0.5)
                    continue
                probe = client.get(f"{origin}/api/me", headers=headers)
                if probe.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    return False


def run_local_chat() -> int:
    console = Console()
    handle = start_local_server(console)
    if handle is None:
        return 1
    config = ServerConfig(
        server_url=handle.base_url,
        supabase_url="",
        supabase_publishable_key="",
    )
    auth = LocalStandaloneAuth(token=handle.token)
    console.print(
        "[dim]Local mode: single user, no sign-in. Chat uses the HTTP API on loopback.[/dim]\n"
    )
    try:
        return run_terminal_chat(console, config, auth=auth)
    finally:
        console.print("\n[dim]Stopping local server…[/dim]")
        handle.process.terminate()
        try:
            handle.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            handle.process.kill()