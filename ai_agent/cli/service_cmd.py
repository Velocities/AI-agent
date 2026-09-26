"""Delegate production lifecycle commands to systemd.

The application does not daemonize itself. `ai-agent serve` is the foreground
process systemd runs. These commands only call systemctl, and they do not use
sudo.
"""

from __future__ import annotations

import subprocess
import sys

UNIT = "ai-agent.service"
_ACTIONS = frozenset({"start", "stop", "restart", "status"})


def unit_load_state() -> str:
    result = subprocess.run(
        ["systemctl", "show", "-p", "LoadState", "--value", UNIT],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unknown"


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in _ACTIONS:
        print("usage: ai-agent {start|stop|restart|status|serve}", file=sys.stderr)
        return 2
    action = argv[0]
    try:
        state = unit_load_state()
    except FileNotFoundError:
        _missing_systemctl()
        return 1
    if state == "not-found":
        print(
            "The ai-agent systemd unit is not installed.\n"
            "Foreground (development): ai-agent serve\n"
            "Install the service: sudo deploy/systemd/install.sh",
            file=sys.stderr,
        )
        return 1

    command = ["systemctl", action, UNIT]
    if action == "status":
        command = ["systemctl", "status", UNIT, "--no-pager", "--full"]
    try:
        result = subprocess.run(command, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        _missing_systemctl()
        return 1
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")
    if result.returncode != 0 and action != "status" and _needs_privileges(result.stderr):
        print(
            f"Permission denied. Run: sudo systemctl {action} ai-agent",
            file=sys.stderr,
        )
    return result.returncode


def _missing_systemctl() -> None:
    print(
        "systemctl is not available. This machine is not using the systemd service.\n"
        "Run the application in the foreground with: ai-agent serve",
        file=sys.stderr,
    )


def _needs_privileges(stderr: str) -> bool:
    lowered = stderr.lower()
    markers = (
        "access denied",
        "authentication",
        "permission denied",
        "not authorized",
        "insufficient permissions",
    )
    return any(marker in lowered for marker in markers)
