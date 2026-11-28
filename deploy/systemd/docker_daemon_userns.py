"""Turn Docker user-namespace remapping on, or remove it after a failed restart.

``enable`` writes ``"userns-remap": "default"`` into /etc/docker/daemon.json.
A value that is already set to something else is left unchanged and the
process exits non-zero. ``revert`` removes the key the installer added.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_DAEMON = Path("/etc/docker/daemon.json")


def enable(path: Path = _DAEMON) -> None:
    data: dict = {}
    if path.exists() and path.read_text(encoding="utf-8").strip():
        data = json.loads(path.read_text(encoding="utf-8"))
    current = data.get("userns-remap")
    if current not in (None, "default"):
        raise SystemExit(f"leave-userns:{current}")
    data["userns-remap"] = "default"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def revert(path: Path = _DAEMON) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("userns-remap", None)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if argv == ["enable"]:
        enable()
        return 0
    if argv == ["revert"]:
        revert()
        return 0
    print("usage: docker_daemon_userns.py enable|revert", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
