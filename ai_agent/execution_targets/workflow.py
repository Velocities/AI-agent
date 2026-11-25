"""Run model commands inside one workflow container.

The container name is fixed when the target is built. Command argv is
appended to a host-built ``docker exec`` prefix. ``write_file`` is translated
into a write inside ``/work`` and is not handed to the host executor.
"""

from __future__ import annotations

from ai_agent.commands.ast import CommandExpr, SingleCommand, WriteFileCommand
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.commands.render import render_command
from ai_agent.docker_broker.authorize import BrokerRejected, authorize, plan_target_exec
from ai_agent.execution_targets.base import ExecutionTarget
from ai_agent.execution_targets.remote_script import render_posix_script

WORK_ROOT = "/work"
WORKFLOW_TARGET_NAME = "workflow"


class WorkflowPathEscape(ValueError):
    """A path would leave the workflow container work directory."""


class WorkflowExecutionTarget(ExecutionTarget):
    kind = "workflow"

    def __init__(
        self,
        *,
        container: str,
        executor: CommandExecutor,
        workflow_name: str,
        name: str = WORKFLOW_TARGET_NAME,
        description: str = "",
        docker_bin: str = "docker",
        broker=None,
    ):
        if not container or container.startswith("-") or "/" in container:
            raise WorkflowPathEscape(f"Invalid workflow container name {container!r}.")
        if "/" in docker_bin or docker_bin.startswith("-"):
            raise WorkflowPathEscape("docker_bin must be a command name.")
        self.name = name
        self.description = description or f"Workflow {workflow_name} container"
        self.container = container
        self.workflow_name = workflow_name
        self.docker_bin = docker_bin
        self._executor = executor
        self._broker = broker

    def display(self) -> str:
        return f"{self.name} (workflow {self.workflow_name})"

    @property
    def uses_host_policy(self) -> bool:
        # Confinement is the container, /work layout, and broker exec whitelist.
        # default_policy.yaml applies to the host agent user, not argv inside Docker.
        return False

    def run(self, expr: CommandExpr) -> CommandResult:
        try:
            if isinstance(expr, WriteFileCommand):
                return self._write_file(expr)
            if isinstance(expr, SingleCommand):
                cwd = _workflow_cwd(expr.cwd)
                argv = list(expr.argv)
                script = None
            else:
                cwd = WORK_ROOT
                argv = None
                script = render_posix_script(expr)
            planned = plan_target_exec(
                container=self.container,
                cwd=cwd,
                argv=argv,
                script=script,
                docker_bin=self.docker_bin,
            )
        except (WorkflowPathEscape, BrokerRejected) as exc:
            return self._rejected(expr, str(exc))
        return self._finish(
            planned,
            expr=expr,
            cwd=cwd,
            argv=argv,
            script=script,
            stdin=None,
            rendered=render_command(expr),
            extra={},
        )

    def run_tool(self, entrypoint: str, stdin_text: str) -> CommandResult:
        """Exec a manifest entrypoint with JSON on stdin. The path is not from the model."""
        if "/" in entrypoint or entrypoint.startswith("-") or not entrypoint:
            return self._rejected_message(f"Refusing tool entrypoint {entrypoint!r}.")
        try:
            planned = plan_target_exec(
                container=self.container,
                cwd=WORK_ROOT,
                argv=[entrypoint],
                docker_bin=self.docker_bin,
            )
        except BrokerRejected as exc:
            return self._rejected_message(str(exc))
        result = self._finish(
            planned,
            expr=None,
            cwd=WORK_ROOT,
            argv=[entrypoint],
            script=None,
            stdin=stdin_text,
            rendered=entrypoint,
            extra={"workflow_tool": entrypoint},
        )
        return result

    def docker_argv(self, expr: CommandExpr) -> list[str]:
        if isinstance(expr, SingleCommand):
            return plan_target_exec(
                container=self.container,
                cwd=_workflow_cwd(expr.cwd),
                argv=list(expr.argv),
                docker_bin=self.docker_bin,
            )
        return plan_target_exec(
            container=self.container,
            cwd=WORK_ROOT,
            script=render_posix_script(expr),
            docker_bin=self.docker_bin,
        )

    def _write_file(self, expr: WriteFileCommand) -> CommandResult:
        path = confine_work_path(expr.path)
        redirect = ">>" if expr.append else ">"
        script = f'mkdir -p "$(dirname "$1")" && cat {redirect} "$1"'
        script_args = ["sh", path]
        try:
            planned = plan_target_exec(
                container=self.container,
                cwd=WORK_ROOT,
                script=script,
                script_args=script_args,
                docker_bin=self.docker_bin,
            )
        except BrokerRejected as exc:
            return self._rejected(expr, str(exc))
        return self._finish(
            planned,
            expr=expr,
            cwd=WORK_ROOT,
            argv=None,
            script=script,
            script_args=script_args,
            stdin=expr.content,
            rendered=render_command(expr),
            extra={},
        )

    def _finish(
        self,
        planned: list[str],
        *,
        expr: CommandExpr | None,
        cwd: str,
        argv: list[str] | None,
        script: str | None,
        stdin: str | None,
        rendered: str,
        extra: dict,
        script_args: list[str] | None = None,
    ) -> CommandResult:
        try:
            authorize(planned)
        except BrokerRejected as exc:
            if expr is None:
                return self._rejected_message(str(exc))
            return self._rejected(expr, str(exc))
        if self._broker is not None:
            try:
                completed = self._broker.exec(
                    container=self.container,
                    cwd=cwd,
                    argv=argv,
                    script=script,
                    script_args=script_args,
                    stdin=stdin,
                    timeout=self._timeout(),
                )
            except BrokerRejected as exc:
                if expr is None:
                    return self._rejected_message(str(exc))
                return self._rejected(expr, str(exc))
            result = CommandResult(
                success=completed.returncode == 0,
                exit_status=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                duration_ms=0,
                rendered=rendered,
            )
        else:
            result = self._executor.run_argv(planned, stdin_text=stdin)
            result.rendered = rendered
        result.metadata = {
            **(result.metadata or {}),
            "execution_target": self.name,
            "workflow": self.workflow_name,
            "container": self.container,
            **extra,
        }
        return result

    def _timeout(self) -> float:
        value = getattr(self._executor, "timeout", 120)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return 120
        return float(value)

    def _rejected(self, expr: CommandExpr, message: str) -> CommandResult:
        return CommandResult(
            success=False,
            exit_status=126,
            stdout="",
            stderr=message,
            duration_ms=0,
            rendered=render_command(expr),
            metadata={"execution_target": self.name, "workflow_rejected": True},
        )

    def _rejected_message(self, message: str) -> CommandResult:
        return CommandResult(
            success=False,
            exit_status=126,
            stdout="",
            stderr=message,
            duration_ms=0,
            rendered="",
            metadata={"execution_target": self.name, "workflow_rejected": True},
        )


def _workflow_cwd(cwd: str | None) -> str:
    """Workflow commands stay under /work. The path is inside the container."""
    chosen = cwd or WORK_ROOT
    if chosen != WORK_ROOT and not chosen.startswith(WORK_ROOT + "/"):
        raise WorkflowPathEscape("Commands in a workflow stay under /work.")
    if any(part in {".", ".."} for part in chosen.split("/")):
        raise WorkflowPathEscape("Commands in a workflow stay under /work.")
    return chosen


def confine_work_path(path: str) -> str:
    """Lexically force a write_file path to stay under /work."""
    if not isinstance(path, str) or not path.strip() or "\0" in path:
        raise WorkflowPathEscape("write_file path is empty or contains NUL.")
    raw = path if path.startswith("/") else f"{WORK_ROOT}/{path}"
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise WorkflowPathEscape("write_file path cannot contain '..'.")
        parts.append(part)
    if not parts or parts[0] != "work":
        raise WorkflowPathEscape("write_file only writes under /work inside the workflow container.")
    return "/" + "/".join(parts)