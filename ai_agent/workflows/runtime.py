"""Bind a stored conversation to its workflow container.

Clients choose a workflow by name. The server owns the container name, the
sleep directory, and the Docker process.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_agent.workflows.container import SLEEP_ROOT
from ai_agent.workflows.manifests import WorkflowError, default_workflow_image_root
from ai_agent.workflows.session import WorkflowSession, bind_workflow

logger = logging.getLogger(__name__)


class WorkflowRuntimeError(RuntimeError):
    """The workflow container could not be started."""


@dataclass(frozen=True)
class WorkflowAttachment:
    name: str
    parameters: dict[str, str]
    container_name: str
    sleep_dir: Path
    user_id: str
    conversation_id: str


def container_name_for(conversation_id: str) -> str:
    compact = conversation_id.replace("-", "")
    if not compact.isalnum():
        raise WorkflowError("Conversation id cannot name a container.")
    return f"wf{compact[:32]}"


def sleep_dir_for(user_id: str, conversation_id: str, *, sleep_root: Path = SLEEP_ROOT) -> Path:
    if _unsafe_path_part(user_id) or _unsafe_path_part(conversation_id):
        raise WorkflowError("Workflow sleep path is not a single directory name.")
    return sleep_root / user_id / conversation_id


def attachment_for(
    *,
    user_id: str,
    conversation_id: str,
    workflow_name: str,
    parameters: dict[str, str],
) -> WorkflowAttachment:
    return WorkflowAttachment(
        name=workflow_name,
        parameters=dict(parameters),
        container_name=container_name_for(conversation_id),
        sleep_dir=sleep_dir_for(user_id, conversation_id),
        user_id=user_id,
        conversation_id=conversation_id,
    )


def open_attached_workflow(
    attachment: WorkflowAttachment,
    linux_username: str,
    *,
    workflow_image_root: Path | None = None,
) -> WorkflowSession:
    return bind_workflow(
        workflow_image_root or default_workflow_image_root(),
        attachment.name,
        linux_username=linux_username,
        container_name=attachment.container_name,
        sleep_dir=attachment.sleep_dir,
        parameters=attachment.parameters,
    )


def start_workflow_container(
    attachment: WorkflowAttachment,
    linux_username: str,
    *,
    workflow_image_root: Path | None = None,
) -> WorkflowSession:
    """Create or start the conversation's container and write session.json."""
    session = open_attached_workflow(
        attachment,
        linux_username,
        workflow_image_root=workflow_image_root,
    )
    ensure_workflow_container(session)
    return session


def ensure_workflow_container(session: WorkflowSession) -> None:
    sleep = next(mount.source for mount in session.spec.mounts if mount.target == "/work")
    try:
        sleep.mkdir(parents=True, exist_ok=True)
        # Container root is a remapped, unprivileged host uid, so /work must be
        # open to "other". The sleep root above it is 2770, so host users
        # outside the service group still cannot reach this directory.
        sleep.chmod(0o777)
    except OSError as exc:
        raise WorkflowRuntimeError(
            f"Could not create the workflow sleep directory {sleep}: {exc}"
        ) from exc
    docker = session.spec.docker_bin
    inspect = _docker(
        docker,
        "inspect",
        "-f",
        "{{.State.Running}}",
        session.container_name,
    )
    if inspect.returncode != 0:
        started = _docker(docker, *session.spec.run_argv()[1:])
        if started.returncode != 0:
            detail = (started.stderr or started.stdout).strip()
            raise WorkflowRuntimeError(
                detail
                or f"Could not start workflow image {session.image}. "
                "Build it with the workflow image Dockerfile before opening this workflow."
            )
    elif inspect.stdout.strip() != "true":
        resumed = _docker(docker, "start", session.container_name)
        if resumed.returncode != 0:
            detail = (resumed.stderr or resumed.stdout).strip()
            raise WorkflowRuntimeError(detail or "Could not resume the workflow container.")
    _write_session_file(session)


def stop_workflow_container(container_name: str, *, docker_bin: str = "docker") -> None:
    """Stop a workflow container. The sleep directory is left in place."""
    if not container_name or container_name.startswith("-"):
        return
    result = _docker(docker_bin, "rm", "-f", container_name)
    if result.returncode != 0:
        logger.warning(
            "Could not remove workflow container %s: %s",
            container_name,
            (result.stderr or result.stdout).strip(),
        )


def _write_session_file(session: WorkflowSession) -> None:
    payload = json.dumps(session.session_file())
    result = _docker(
        session.spec.docker_bin,
        "exec",
        "-i",
        session.container_name,
        "/bin/sh",
        "-c",
        "cat > /work/session.json",
        stdin=payload,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise WorkflowRuntimeError(detail or "Could not write /work/session.json.")


def _docker(docker_bin: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Ask the Docker broker. The API process does not open the Docker socket."""
    from ai_agent.docker_broker.client import default_docker_broker

    return default_docker_broker().invoke(
        [docker_bin, *args],
        timeout=120,
        stdin=stdin,
    )


def _unsafe_path_part(value: str) -> bool:
    return (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\0" in value
    )
