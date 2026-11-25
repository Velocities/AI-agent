"""Host layout for the Docker broker process only.

BuildKit and the Docker CLI need a writable ``HOME`` and ``DOCKER_CONFIG``.
That belongs to the broker identity (``ai-docker``), not to the API or
workflow lifecycle. Other packages must not import this module.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BROKER_STATE_ROOT = Path("/var/lib/ai-docker")
_ENV_STATE_ROOT = "AI_AGENT_DOCKER_BROKER_STATE"


def broker_state_root() -> Path:
    """Directory that acts as the broker user's home on disk."""
    raw = os.environ.get(_ENV_STATE_ROOT, "").strip()
    if raw:
        return Path(raw)
    return DEFAULT_BROKER_STATE_ROOT


def docker_config_dir(state_root: Path | None = None) -> Path:
    root = state_root if state_root is not None else broker_state_root()
    return root / ".docker"


def broker_subprocess_env(*, base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for ``docker`` / ``buildx`` child processes in the broker."""
    root = broker_state_root()
    env = dict(base if base is not None else os.environ)
    env["HOME"] = str(root)
    env["DOCKER_CONFIG"] = str(docker_config_dir(root))
    env.setdefault("USER", env.get("LOGNAME", "ai-docker"))
    return env


class UsernsRemapGuard:
    """Refuse workflow containers unless dockerd remaps container root.

    ``docker run --userns`` cannot request remapping; only the daemon's
    ``userns-remap`` setting does. A positive answer is cached for the life of
    the broker; a negative one is re-checked so fixing dockerd needs no restart.
    """

    def __init__(self) -> None:
        self._confirmed = False
        self._lock = threading.Lock()

    def __call__(self) -> str | None:
        with self._lock:
            if self._confirmed:
                return None
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{range .SecurityOptions}}{{.}} {{end}}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=broker_subprocess_env(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"Could not ask dockerd for its security options: {exc}"
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return f"Could not ask dockerd for its security options: {detail}"
        if "name=userns" not in result.stdout:
            return (
                "dockerd is not running with userns-remap, so root in a workflow "
                "container would be root on the host. Re-run "
                "sudo deploy/systemd/install.sh to enable it."
            )
        with self._lock:
            self._confirmed = True
        return None


def prepare_broker_host_runtime() -> Path:
    """Ensure buildx state directories exist when the broker can create them."""
    root = broker_state_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        docker_config_dir(root).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "Docker broker could not create state under %s: %s "
            "(systemd StateDirectory or the installer should provide this).",
            root,
            exc,
        )
    else:
        logger.info("Docker broker host state: HOME=%s", root)
    return root