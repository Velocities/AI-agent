"""Turn a Docker intent into argv, or refuse it.

Every accepted command is a list that starts with the literal name ``docker``.
Nothing here joins that list into a shell string. A refused command raises
before any runner is called, so it never becomes a host process.
"""

from __future__ import annotations

import re
from pathlib import Path

from ai_agent.workflows.container import (
    SLEEP_ROOT,
    ContainerMount,
    WorkflowContainerSpec,
    WorkflowSpecError,
)

class BrokerRejected(ValueError):
    """The request would not stay inside a container. It was not executed."""


_CONTAINER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_WORKFLOW_CONTAINER = re.compile(r"^wf[0-9a-f]{8,32}$")
_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$|^[0-9]{1,10}$")
_TAG = re.compile(r"^ai-agent-workflow:[A-Za-z][A-Za-z0-9._-]{0,63}-[0-9a-f]{16}$")
_WORKFLOW_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_NIX_SYSTEMS = {"x86_64-linux", "aarch64-linux"}
_WORKDIR_PART = re.compile(r"[A-Za-z0-9._@%+=,~-]{1,64}")


def plan_target_exec(
    *,
    container: str,
    user: str = "",
    cwd: str | None = None,
    argv: list[str] | None = None,
    script: str | None = None,
    script_args: list[str] | None = None,
    docker_bin: str = "docker",
) -> list[str]:
    """argv for ``docker exec`` into one already-chosen container.

    ``container`` and ``user`` come from the stored target, not from the
    command the model sent. The command is appended after the container name,
    so its text cannot become a Docker flag or a host shell.
    """
    if docker_bin != "docker":
        raise BrokerRejected(
            "The Docker program is fixed. A path or another program cannot be substituted."
        )
    if not isinstance(container, str) or not _CONTAINER.fullmatch(container):
        raise BrokerRejected("Container name is not a single Docker name.")
    if user and (not isinstance(user, str) or not _USER.fullmatch(user)):
        raise BrokerRejected("Docker user must be a name or a uid, not an option.")
    planned = ["docker", "exec", "-i"]
    if user:
        planned.extend(["-u", user])
    if cwd is not None:
        if not _safe_workdir(cwd):
            raise BrokerRejected("Working directory is not a path inside the container.")
        planned.extend(["-w", cwd])
    planned.append(container)
    if script is not None:
        if argv is not None:
            raise BrokerRejected("An exec is either a command or a script, not both.")
        if not isinstance(script, str) or "\0" in script:
            raise BrokerRejected("Script is empty or contains NUL.")
        planned.extend(["/bin/sh", "-c", script])
        if script_args is not None:
            if not isinstance(script_args, list) or any(
                not isinstance(part, str) or part == "" or "\0" in part for part in script_args
            ):
                raise BrokerRejected("Script arguments must be strings without NUL.")
            planned.extend(script_args)
        return planned
    if script_args:
        raise BrokerRejected("Script arguments require a script.")
    if not argv or not isinstance(argv, list):
        raise BrokerRejected("Command is empty.")
    if any(not isinstance(part, str) or part == "" or "\0" in part for part in argv):
        raise BrokerRejected("Command arguments must be strings without NUL.")
    planned.extend(argv)
    return planned


def authorize(
    argv: list[str],
    *,
    workflow_image_root: Path | None = None,
    sleep_root: Path = SLEEP_ROOT,
) -> list[str]:
    """Accept one of the known Docker operations. Anything else is refused."""
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(part, str) or "\0" in part for part in argv)
    ):
        raise BrokerRejected("Docker argv must be a list of strings.")
    if argv[0] != "docker":
        raise BrokerRejected(
            "Only the docker command is accepted, and it cannot be a path or a shell."
        )
    if argv[1:3] == ["exec", "-i"]:
        return _authorize_exec(argv)
    if argv[1:3] == ["image", "inspect"]:
        return _authorize_image_inspect(argv)
    if argv[1:3] == ["buildx", "build"]:
        return _authorize_build(argv, workflow_image_root)
    if len(argv) > 1 and argv[1] == "run":
        return _authorize_run(argv, sleep_root)
    if argv[1:3] == ["rm", "-f"]:
        return _authorize_workflow_name(argv, position=3, label="rm")
    if len(argv) > 1 and argv[1] == "start":
        return _authorize_workflow_name(argv, position=2, label="start")
    if len(argv) > 1 and argv[1] == "inspect":
        return _authorize_container_inspect(argv)
    preview = _argv_preview(argv)
    raise BrokerRejected(
        "Docker operation not allowed through the broker: "
        f"{preview}. "
        "Allowed: docker exec -i, docker buildx build --load, docker image inspect, "
        "docker run, docker rm -f, docker start, docker inspect."
    )


def _authorize_exec(argv: list[str]) -> list[str]:
    rest = argv[3:]
    if rest[:1] == ["-u"]:
        if len(rest) < 2 or not _USER.fullmatch(rest[1]):
            raise BrokerRejected("Refusing the docker exec user.")
        rest = rest[2:]
    if rest[:1] == ["-w"]:
        if len(rest) < 2 or not _safe_workdir(rest[1]):
            raise BrokerRejected("Refusing the docker exec working directory.")
        rest = rest[2:]
    if len(rest) < 2 or not _CONTAINER.fullmatch(rest[0]):
        raise BrokerRejected("docker exec needs one container and a command inside it.")
    if any(part == "" for part in rest[1:]):
        raise BrokerRejected("Command arguments must not be empty.")
    return argv


def _authorize_image_inspect(argv: list[str]) -> list[str]:
    if len(argv) != 6 or argv[:5] != ["docker", "image", "inspect", "--format", "{{.Id}}"]:
        raise BrokerRejected("Image inspect has a fixed form.")
    if not _TAG.fullmatch(argv[5]):
        raise BrokerRejected("Image inspect only accepts a workflow image tag.")
    return argv


def _authorize_build(argv: list[str], workflow_image_root: Path | None) -> list[str]:
    if workflow_image_root is None:
        raise BrokerRejected("The broker has no workflow image root configured.")
    if (
        len(argv) != 11
        or argv[:4] != ["docker", "buildx", "build", "--load"]
        or argv[4] != "--build-arg"
    ):
        raise BrokerRejected("Image builds use BuildKit and the generic workflow Dockerfile only.")
    if not argv[5].startswith("WORKFLOW="):
        raise BrokerRejected("Image builds use BuildKit and the generic workflow Dockerfile only.")
    name = argv[5].split("=", 1)[1]
    if not _WORKFLOW_NAME.fullmatch(name):
        raise BrokerRejected("Workflow name is not a single token.")
    system = argv[7].split("=", 1)[1] if argv[6] == "--build-arg" and "=" in argv[7] else ""
    if system not in _NIX_SYSTEMS or argv[8] != "-t":
        raise BrokerRejected("Image builds use BuildKit and the generic workflow Dockerfile only.")
    tag = argv[9]
    prefix = f"ai-agent-workflow:{name}-"
    fingerprint = tag[len(prefix):] if tag.startswith(prefix) else ""
    if not re.fullmatch(r"[0-9a-f]{16}", fingerprint):
        raise BrokerRejected("The image tag does not match this workflow.")
    try:
        context = Path(argv[10]).resolve()
        allowed = Path(workflow_image_root).resolve()
    except OSError as exc:
        raise BrokerRejected(f"Build context cannot be resolved: {exc}") from exc
    if context != allowed:
        raise BrokerRejected("The build context is the configured workflow_image tree.")
    return argv


_RUN_FLAGS = [
    "--security-opt",
    "no-new-privileges",
    "--cap-drop",
    "SYS_ADMIN",
    "--pids-limit",
    "256",
    "--network",
    "bridge",
]


def _authorize_run(argv: list[str], sleep_root: Path) -> list[str]:
    first_mount = 5 + len(_RUN_FLAGS)
    if argv[:4] != ["docker", "run", "-d", "--name"] or len(argv) < first_mount + 5:
        raise BrokerRejected(
            "docker run must be: docker run -d --name <workflow container> "
            "<fixed security flags> --mount ... <workflow image> sleep infinity."
        )
    name = argv[4]
    if not _WORKFLOW_CONTAINER.fullmatch(name):
        raise BrokerRejected("Workflow container names are assigned by the agent.")
    if argv[5:first_mount] != _RUN_FLAGS:
        raise BrokerRejected(
            "docker run security flags must be exactly: " + " ".join(_RUN_FLAGS)
        )
    if argv[-2:] != ["sleep", "infinity"]:
        raise BrokerRejected("A workflow container can only be started to sleep.")
    image = argv[-3]
    if not _TAG.fullmatch(image):
        raise BrokerRejected("A workflow container can only use a workflow image.")
    mount_args = argv[first_mount:-3]
    if len(mount_args) % 2 != 0:
        raise BrokerRejected("Refusing to start a container with those arguments.")
    mounts: list[ContainerMount] = []
    for flag, value in zip(mount_args[0::2], mount_args[1::2], strict=True):
        if flag != "--mount":
            raise BrokerRejected("Workflow containers do not accept extra Docker options.")
        mounts.append(_parse_mount(value))
    spec = WorkflowContainerSpec(
        image=image,
        container_name=name,
        mounts=tuple(mounts),
        network="bridge",
        sleep_root=sleep_root,
        docker_bin="docker",
    )
    try:
        expected = spec.run_argv()
    except WorkflowSpecError as exc:
        raise BrokerRejected(str(exc)) from exc
    if argv != expected:
        raise BrokerRejected(
            "docker run does not match the validated container spec: "
            f"expected {_argv_preview(expected, limit=40)}"
        )
    return argv


def _authorize_container_inspect(argv: list[str]) -> list[str]:
    if len(argv) != 5 or argv[:4] != ["docker", "inspect", "-f", "{{.State.Running}}"]:
        raise BrokerRejected("Container inspect has a fixed form.")
    if not _WORKFLOW_CONTAINER.fullmatch(argv[4]):
        raise BrokerRejected("Container inspect only accepts a workflow container.")
    return argv


def _authorize_workflow_name(argv: list[str], *, position: int, label: str) -> list[str]:
    if len(argv) != position + 1 or not _WORKFLOW_CONTAINER.fullmatch(argv[position]):
        raise BrokerRejected(f"docker {label} only accepts a workflow container.")
    return argv


def _parse_mount(value: str) -> ContainerMount:
    if not value or "\n" in value or "\0" in value:
        raise BrokerRejected("Refusing an empty or multi-line mount.")
    fields: dict[str, str] = {}
    flags: set[str] = set()
    for item in value.split(","):
        if "=" not in item:
            flags.add(item)
            continue
        key, raw = item.split("=", 1)
        fields[key] = raw
    if fields.get("type") != "bind":
        raise BrokerRejected(f"Refusing mount {value!r}: only type=bind is allowed.")
    if set(fields) != {"type", "source", "target"} or flags not in (set(), {"readonly"}):
        raise BrokerRejected(
            f"Refusing mount {value!r}: only source, target, and readonly are allowed."
        )
    source = fields["source"]
    target = fields["target"]
    if not source.startswith("/") or not target.startswith("/"):
        raise BrokerRejected(f"Refusing mount {value!r}: paths must be absolute.")
    if target == "/nix/store" and source != "/nix/store":
        raise BrokerRejected("The Nix store mount can only be the host /nix/store.")
    return ContainerMount(source=Path(source), target=target, read_only="readonly" in flags)


def _argv_preview(argv: list[str], *, limit: int = 8) -> str:
    head = argv[:limit]
    text = " ".join(head)
    if len(argv) > limit:
        text += " …"
    return text


def _safe_workdir(cwd: str) -> bool:
    if not isinstance(cwd, str) or not cwd.startswith("/") or cwd == "/":
        return False
    if "docker.sock" in cwd:
        return False
    parts = cwd.split("/")
    if any(part == "" for part in parts[1:]):
        return False
    return all(part not in {".", ".."} and _WORKDIR_PART.fullmatch(part) for part in parts[1:])
