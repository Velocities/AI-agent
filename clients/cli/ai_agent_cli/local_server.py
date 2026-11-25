"""Start ai-agent serve in local standalone mode and open a terminal chat session."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx
from rich.console import Console

from ai_agent_cli.auth.local import LocalStandaloneAuth
from ai_agent_cli.contracts import DEFAULT_LOCAL_STANDALONE_USER_ID
from ai_agent_cli.client_state import ServerConfig
from ai_agent_cli.terminal_chat import run_terminal_chat


@dataclass
class LocalServerProcess:
    process: subprocess.Popen[bytes]
    base_url: str
    token: str


def _default_api_url() -> str:
    host = os.environ.get("API_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.environ.get("API_BIND_PORT", "8000").strip() or "8000"
    display = "127.0.0.1" if host.lower() == "localhost" else host
    return f"http://{display}:{port}"


def start_local_server(console: Console) -> LocalServerProcess | None:
    token = secrets.token_urlsafe(32)
    base_url = _default_api_url()
    env = os.environ.copy()
    env["LOCAL_STANDALONE_MODE"] = "1"
    env["LOCAL_STANDALONE_TOKEN"] = token
    env.setdefault("LOCAL_STANDALONE_USER_ID", DEFAULT_LOCAL_STANDALONE_USER_ID)
    command = [sys.executable, "-m", "ai_agent.service.supervisor"]
    console.print("[dim]Starting local agent server (ai-agent serve)…[/dim]")
    try:
        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        console.print(f"[red]Could not start the local server:[/red] {exc}")
        return None
    if not _wait_for_health(base_url):
        console.print("[red]Local server did not become ready.[/red]")
        try:
            process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        if process.stderr:
            detail = process.stderr.read().decode("utf-8", errors="replace").strip()
            if detail:
                console.print(f"[dim]{detail[-2000:]}[/dim]")
        return None
    return LocalServerProcess(process=process, base_url=base_url, token=token)


def _wait_for_health(base_url: str, *, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(f"{base_url.rstrip('/')}/health")
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
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
            handle.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            handle.process.kill()