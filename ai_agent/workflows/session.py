"""One running workflow: a manifest, a container spec, and session parameters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_agent.commands.executor import CommandExecutor
from ai_agent.execution_targets.router import ExecutionTargetRouter
from ai_agent.execution_targets.sandbox import SandboxExecutionTarget
from ai_agent.workflows.container import (
    SLEEP_ROOT,
    ContainerMount,
    SandboxContainerSpec,
)
from ai_agent.workflows.image import image_tag
from ai_agent.workflows.manifests import (
    WorkflowManifest,
    load_workflow,
    session_document,
    validate_parameters,
)


@dataclass(frozen=True)
class WorkflowSession:
    manifest: WorkflowManifest
    container_name: str
    image: str
    parameters: dict[str, str]
    spec: SandboxContainerSpec
    linux_username: str

    def session_file(self) -> dict:
        return session_document(self.manifest, self.parameters)

    def target(self, executor: CommandExecutor, broker=None) -> SandboxExecutionTarget:
        return SandboxExecutionTarget(
            container=self.container_name,
            executor=executor,
            workflow_name=self.manifest.name,
            description=self.manifest.description,
            broker=broker,
        )


def bind_workflow(
    sandbox_root: Path,
    workflow_name: str,
    *,
    linux_username: str,
    container_name: str,
    sleep_dir: Path,
    parameters: dict[str, str] | None = None,
    nix_store: Path | None = None,
    sleep_root: Path = SLEEP_ROOT,
) -> WorkflowSession:
    """Validate a session. This does not start Docker."""
    if not linux_username.strip():
        raise ValueError("linux_username is required to bind a workflow session.")
    manifest = load_workflow(sandbox_root, workflow_name)
    stored = validate_parameters(manifest, parameters)
    mounts = [
        ContainerMount(source=sleep_dir, target="/work", read_only=False),
    ]
    if nix_store is not None:
        mounts.append(
            ContainerMount(source=nix_store, target="/nix/store", read_only=True)
        )
    spec = SandboxContainerSpec(
        image=image_tag(manifest, sandbox_root),
        container_name=container_name,
        mounts=tuple(mounts),
        sleep_root=sleep_root,
    )
    spec.run_argv()
    return WorkflowSession(
        manifest=manifest,
        container_name=container_name,
        image=spec.image,
        parameters=stored,
        spec=spec,
        linux_username=linux_username.strip(),
    )


def router_for_workflow(
    executor: CommandExecutor,
    session: WorkflowSession,
    broker=None,
) -> ExecutionTargetRouter:
    """The model sees only the sandbox target."""
    target = session.target(executor, broker=broker)
    return ExecutionTargetRouter({target.name: target}, default_name=target.name)
