from __future__ import annotations

import logging

from ai_agent.commands.executor import CommandExecutor
from ai_agent.execution_targets.base import (
    ExecutionTarget,
    TargetSummary,
    UnknownExecutionTarget,
)
from ai_agent.execution_targets.docker import DockerExecutionTarget
from ai_agent.execution_targets.local import LocalExecutionTarget
from ai_agent.execution_targets.ssh import SshExecutionTarget
from ai_agent.execution_targets.store import (
    DockerTargetRecord,
    ExecutionTargetsFile,
    LocalTargetRecord,
    RESERVED_LOCAL_NAME,
    SshTargetRecord,
    TargetConfigError,
    load_targets_file,
)

logger = logging.getLogger(__name__)


class ExecutionTargetRouter:
    """Map a configured name to an ExecutionTarget. The model only supplies names."""

    def __init__(
        self,
        targets: dict[str, ExecutionTarget],
        *,
        default_name: str = RESERVED_LOCAL_NAME,
    ):
        if not targets:
            raise TargetConfigError("At least one execution target is required")
        if default_name not in targets:
            allowed = ", ".join(sorted(targets))
            raise TargetConfigError(
                f"Default execution target {default_name!r} is not configured. "
                f"Choose one of: {allowed}"
            )
        self._targets = dict(targets)
        self.default_name = default_name

    @classmethod
    def local_only(cls, executor: CommandExecutor) -> ExecutionTargetRouter:
        local = LocalExecutionTarget(executor)
        return cls({local.name: local}, default_name=local.name)

    def names(self) -> list[str]:
        return list(self._targets)

    def summaries(self) -> list[TargetSummary]:
        return [target.summary() for target in self._targets.values()]

    def resolve(self, name: str) -> ExecutionTarget:
        try:
            return self._targets[name]
        except KeyError as exc:
            allowed = ", ".join(self.names()) or "(none)"
            raise UnknownExecutionTarget(
                f"Unknown execution target {name!r}. Configured targets: {allowed}"
            ) from exc


def build_router(
    executor: CommandExecutor,
    document: ExecutionTargetsFile,
) -> ExecutionTargetRouter:
    targets: dict[str, ExecutionTarget] = {}
    for name, record in document.execution_targets.items():
        targets[name] = _build_target(name, record, executor)
    if RESERVED_LOCAL_NAME not in targets:
        targets[RESERVED_LOCAL_NAME] = LocalExecutionTarget(executor)
    return ExecutionTargetRouter(targets, default_name=document.default_target)


def load_router(
    executor: CommandExecutor,
    path,
    *,
    default_override: str | None = None,
) -> ExecutionTargetRouter:
    # Legacy: loads global execution_targets.yaml. Per-user routers will be built
    # from SQLite + SecureKeyStore (docs/execution-targets.md); this path goes away.
    document = load_targets_file(path)
    if default_override:
        if (
            document.default_target_from_file
            and document.default_target != default_override
        ):
            logger.warning(
                "Ignoring default_target %r in %s. AGENT_DEFAULT_TARGET=%r wins; "
                "remove the key from the file to silence this.",
                document.default_target,
                path,
                default_override,
            )
        document = document.model_copy(update={"default_target": default_override})
    return build_router(executor, document)


def _build_target(name: str, record, executor: CommandExecutor) -> ExecutionTarget:
    if isinstance(record, LocalTargetRecord):
        return LocalExecutionTarget(
            executor,
            name=name,
            description=record.description,
        )
    if isinstance(record, SshTargetRecord):
        known = record.known_hosts
        if known is None:
            raise TargetConfigError(f"SSH target {name!r} is missing known_hosts")
        return SshExecutionTarget(
            name=name,
            host=record.host,
            user=record.user,
            port=record.port,
            identity_file=record.identity_file,
            known_hosts=known,
            executor=executor,
            description=record.description,
        )
    if isinstance(record, DockerTargetRecord):
        return DockerExecutionTarget(
            name=name,
            container=record.container,
            executor=executor,
            description=record.description,
            docker_bin=record.docker_bin,
            user=record.user,
        )
    raise TargetConfigError(f"Unsupported target record: {type(record)!r}")
