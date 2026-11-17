"""Host-side container contract for one workflow session.

The model never supplies these arguments. The only writable mount is the
sleep volume, and it has to live under the workflow sleep root so a container
cannot be pointed at the user's home or the agent tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SLEEP_ROOT = Path("/var/lib/ai-agent/workflow-sleep")
WORK_MOUNT = "/work"
NIX_STORE_MOUNT = "/nix/store"
_SOCKET_NAMES = {"docker.sock"}


class SandboxSpecError(ValueError):
    """The container would be able to see or change the host."""


@dataclass(frozen=True)
class ContainerMount:
    source: Path
    target: str
    read_only: bool


@dataclass(frozen=True)
class SandboxContainerSpec:
    image: str
    container_name: str
    user_namespace: str
    mounts: tuple[ContainerMount, ...]
    network: str = "bridge"
    sleep_root: Path = SLEEP_ROOT
    docker_bin: str = "docker"

    def run_argv(self) -> list[str]:
        """docker run argv. Raises when the spec could escape onto the host."""
        validate_spec(self)
        argv = [
            self.docker_bin,
            "run",
            "-d",
            "--name",
            self.container_name,
            "--userns",
            self.user_namespace,
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "SYS_ADMIN",
            "--pids-limit",
            "256",
            "--network",
            self.network,
        ]
        for mount in self.mounts:
            mode = "ro" if mount.read_only else "rw"
            argv.extend(
                [
                    "--mount",
                    "type=bind,"
                    f"source={mount.source},"
                    f"target={mount.target},"
                    f"{mode}",
                ]
            )
        argv.extend([self.image, "sleep", "infinity"])
        return argv


def validate_spec(spec: SandboxContainerSpec) -> None:
    if spec.user_namespace.strip().lower() in {"", "host"}:
        raise SandboxSpecError(
            "Workflow containers require a user namespace such as 'default'. "
            "Root inside the container must not be root on the host."
        )
    if spec.network.strip().lower() == "host":
        raise SandboxSpecError("Workflow containers cannot share the host network.")
    if "/" in spec.docker_bin or spec.docker_bin.startswith("-"):
        raise SandboxSpecError("docker_bin must be a command name, not a path.")
    _require_container_name(spec.container_name)
    work = [mount for mount in spec.mounts if mount.target == WORK_MOUNT]
    if len(work) != 1 or work[0].read_only:
        raise SandboxSpecError("The container needs exactly one writable mount at /work.")
    _require_sleep_source(work[0].source, spec.sleep_root)
    for mount in spec.mounts:
        _reject_host_escape_mount(mount)
    nix = [mount for mount in spec.mounts if mount.target == NIX_STORE_MOUNT]
    if len(nix) > 1 or (nix and not nix[0].read_only):
        raise SandboxSpecError("The Nix store mount must be a single read-only mount.")


def _require_container_name(name: str) -> None:
    if not name or name[0] == "-" or "/" in name or " " in name or "\n" in name:
        raise SandboxSpecError(f"Invalid container name {name!r}.")


def _require_sleep_source(source: Path, sleep_root: Path) -> None:
    try:
        resolved = source.resolve()
        root = sleep_root.resolve()
    except OSError as exc:
        raise SandboxSpecError(f"Sleep volume path cannot be resolved: {exc}") from exc
    if resolved != root and root not in resolved.parents:
        raise SandboxSpecError(
            f"Sleep volume {resolved} must stay under {root}. "
            "It cannot be the user's home or the agent checkout."
        )


def _reject_host_escape_mount(mount: ContainerMount) -> None:
    source = mount.source.as_posix()
    name = mount.source.name
    if name in _SOCKET_NAMES or source.endswith("/docker.sock"):
        raise SandboxSpecError("Workflow containers cannot mount the Docker socket.")
    if mount.target in {"/", "/etc", "/usr", "/bin", "/home", "/root", "/var/run/docker.sock"}:
        raise SandboxSpecError(f"Refusing to mount the host over {mount.target}.")
    if mount.target != WORK_MOUNT and mount.target != NIX_STORE_MOUNT:
        raise SandboxSpecError(
            f"Unexpected mount {mount.target}. Only /work and a read-only /nix/store are allowed."
        )
    if mount.target == WORK_MOUNT and mount.read_only:
        raise SandboxSpecError("/work is the writable sleep volume.")
