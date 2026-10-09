from __future__ import annotations

from ai_agent.commands.executor import CommandExecutor
from ai_agent.execution_targets.base import ExecutionTarget
from ai_agent.execution_targets.docker import DockerExecutionTarget
from ai_agent.execution_targets.local import LocalExecutionTarget
from ai_agent.execution_targets.repository import (
    ExecutionTargetRecord,
    UserExecutionTargetRepository,
)
from ai_agent.execution_targets.router import ExecutionTargetRouter
from ai_agent.execution_targets.secure_key_store import SecureKeyStore
from ai_agent.execution_targets.ssh import SshExecutionTarget
from ai_agent.execution_targets.store import RESERVED_LOCAL_NAME, TargetConfigError


def build_router_for_user(
    *,
    user_id: str,
    linux_username: str,
    executor: CommandExecutor,
    target_repo: UserExecutionTargetRepository,
    key_store: SecureKeyStore,
) -> ExecutionTargetRouter:
    # Per-user default target names may be stored in SQLite later. Until then,
    # omitting target always resolves to local.
    default_name = RESERVED_LOCAL_NAME

    records = target_repo.list_for_user(user_id)
    targets: dict[str, ExecutionTarget] = {
        RESERVED_LOCAL_NAME: LocalExecutionTarget(executor),
    }
    for rec in records:
        if rec.name == RESERVED_LOCAL_NAME:
            raise TargetConfigError("'local' cannot be stored as a user target.")
        if rec.type == "ssh":
            targets[rec.name] = _ssh_from_record(rec, executor, key_store, linux_username)
        elif rec.type == "docker":
            targets[rec.name] = _docker_from_record(rec, executor)
    return ExecutionTargetRouter(targets, default_name=default_name)


def _ssh_from_record(
    rec: ExecutionTargetRecord,
    executor: CommandExecutor,
    key_store: SecureKeyStore,
    linux_username: str,
) -> SshExecutionTarget:
    spec = rec.spec
    host = str(spec.get("host") or "").strip()
    user = str(spec.get("user") or "").strip()
    port = int(spec.get("port") or 22)
    description = str(spec.get("description") or "")
    if not host or not user:
        raise TargetConfigError(f"SSH target {rec.name!r} is missing host or user.")
    identity = key_store.get_identity_private_path(linux_username, rec.id)
    known = key_store.get_known_hosts_path(linux_username, rec.id)
    return SshExecutionTarget(
        name=rec.name,
        host=host,
        user=user,
        port=port,
        identity_file=identity,
        known_hosts=known,
        executor=executor,
        description=description,
    )


def _docker_from_record(
    rec: ExecutionTargetRecord,
    executor: CommandExecutor,
) -> DockerExecutionTarget:
    spec = rec.spec
    container = str(spec.get("container") or "").strip()
    if not container:
        raise TargetConfigError(f"Docker target {rec.name!r} is missing container.")
    return DockerExecutionTarget(
        name=rec.name,
        container=container,
        executor=executor,
        description=str(spec.get("description") or ""),
        docker_bin=str(spec.get("docker_bin") or "docker"),
        user=str(spec.get("user") or ""),
    )
