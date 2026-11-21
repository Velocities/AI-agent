"""API-side client. It sends intents. It does not open the Docker socket."""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

BROKER_SOCKET = Path(os.environ.get("AI_AGENT_DOCKER_BROKER", "/run/ai-agent/docker.sock"))


class SocketDockerBroker:
    """Same calls as :class:`ai_agent.docker_broker.broker.DockerBroker`, over the socket."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else BROKER_SOCKET

    def exec(
        self,
        *,
        container: str,
        user: str = "",
        cwd: str | None = None,
        argv: list[str] | None = None,
        script: str | None = None,
        script_args: list[str] | None = None,
        stdin: str | None = None,
        timeout: float = 120,
    ) -> subprocess.CompletedProcess[str]:
        return self._call(
            {
                "op": "exec",
                "container": container,
                "user": user,
                "cwd": cwd,
                "argv": argv,
                "script": script,
                "script_args": script_args,
                "stdin": stdin,
                "timeout": timeout,
            },
            timeout=timeout,
        )

    def invoke(
        self,
        argv: list[str],
        *,
        timeout: float,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self._call(
            {"op": "invoke", "argv": argv, "stdin": stdin, "timeout": timeout},
            timeout=timeout,
            fallback_argv=argv,
        )

    def _call(
        self,
        message: dict,
        *,
        timeout: float,
        fallback_argv: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = fallback_argv if fallback_argv is not None else ["docker"]
        try:
            raw = _round_trip(self.path, message, timeout=float(timeout) + 30)
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            return subprocess.CompletedProcess(
                argv,
                127,
                "",
                f"Docker broker is not available: {exc}",
            )
        if not raw.get("ok"):
            return subprocess.CompletedProcess(
                argv,
                126,
                "",
                str(raw.get("error") or "Docker broker refused the request."),
            )
        return subprocess.CompletedProcess(
            argv,
            int(raw.get("code") or 0),
            str(raw.get("stdout") or ""),
            str(raw.get("stderr") or ""),
        )


def default_docker_broker() -> SocketDockerBroker:
    return SocketDockerBroker()


def _round_trip(path: Path, message: dict, *, timeout: float) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall(json.dumps(message).encode() + b"\n")
        chunks: list[bytes] = []
        while True:
            block = sock.recv(65536)
            if not block:
                break
            chunks.append(block)
            if b"\n" in block:
                break
    line = b"".join(chunks).split(b"\n", 1)[0]
    if not line:
        raise OSError("Docker broker closed the connection.")
    parsed = json.loads(line.decode())
    if not isinstance(parsed, dict):
        raise OSError("Docker broker returned a non-object.")
    return parsed
