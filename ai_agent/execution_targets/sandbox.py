"""Run model commands inside one workflow container.

The container name is fixed when the target is built. Command argv is
appended to a host-built ``docker exec`` prefix. ``write_file`` is translated
into a write inside ``/work`` and is not handed to the host executor.
"""

from __future__ import annotations

from ai_agent.commands.ast import CommandExpr, SingleCommand, WriteFileCommand
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.commands.render import render_command
from ai_agent.execution_targets.base import ExecutionTarget
from ai_agent.execution_targets.remote_script import render_posix_script

WORK_ROOT = "/work"
SANDBOX_TARGET_NAME = "sandbox"


class SandboxEscape(ValueError):
    """A path would leave the container work directory."""


class SandboxExecutionTarget(ExecutionTarget):
    kind = "sandbox"

    def __init__(
        self,
        *,
        container: str,
        executor: CommandExecutor,
        workflow_name: str,
        name: str = SANDBOX_TARGET_NAME,
        description: str = "",
        docker_bin: str = "docker",
    ):
        if not container or container.startswith("-") or "/" in container:
            raise SandboxEscape(f"Invalid sandbox container name {container!r}.")
        if "/" in docker_bin or docker_bin.startswith("-"):
            raise SandboxEscape("docker_bin must be a command name.")
        self.name = name
        self.description = description or f"Workflow {workflow_name} container"
        self.container = container
        self.workflow_name = workflow_name
        self.docker_bin = docker_bin
        self._executor = executor

    def display(self) -> str:
        return f"{self.name} (workflow {self.workflow_name})"

    def run(self, expr: CommandExpr) -> CommandResult:
        try:
            if isinstance(expr, WriteFileCommand):
                return self._write_file(expr)
            argv = self.docker_argv(expr)
        except SandboxEscape as exc:
            return self._rejected(expr, str(exc))
        result = self._executor.run_argv(argv)
        result.rendered = render_command(expr)
        result.metadata = {
            **(result.metadata or {}),
            "execution_target": self.name,
            "workflow": self.workflow_name,
            "container": self.container,
        }
        return result

    def run_tool(self, entrypoint: str, stdin_text: str) -> CommandResult:
        """Exec a manifest entrypoint with JSON on stdin. The path is not from the model."""
        if "/" in entrypoint or entrypoint.startswith("-"):
            return self._rejected_message(f"Refusing tool entrypoint {entrypoint!r}.")
        argv = [*self._exec_prefix(cwd=WORK_ROOT), entrypoint]
        result = self._executor.run_argv(argv, stdin_text=stdin_text)
        result.rendered = entrypoint
        result.metadata = {
            **(result.metadata or {}),
            "execution_target": self.name,
            "workflow": self.workflow_name,
            "container": self.container,
            "workflow_tool": entrypoint,
        }
        return result

    def docker_argv(self, expr: CommandExpr) -> list[str]:
        if isinstance(expr, SingleCommand):
            return [*self._exec_prefix(cwd=expr.cwd or WORK_ROOT), *expr.argv]
        return [
            *self._exec_prefix(cwd=WORK_ROOT),
            "/bin/sh",
            "-c",
            render_posix_script(expr),
        ]

    def _exec_prefix(self, *, cwd: str) -> list[str]:
        # No -u flag: the container's own root is intentional. The host
        # process that calls docker is the approved user; the daemon's user
        # namespace keeps container root off the host.
        return [
            self.docker_bin,
            "exec",
            "-i",
            "-w",
            cwd,
            self.container,
        ]

    def _write_file(self, expr: WriteFileCommand) -> CommandResult:
        path = confine_work_path(expr.path)
        redirect = ">>" if expr.append else ">"
        argv = [
            *self._exec_prefix(cwd=WORK_ROOT),
            "/bin/sh",
            "-c",
            f'mkdir -p "$(dirname "$1")" && cat {redirect} "$1"',
            "sh",
            path,
        ]
        result = self._executor.run_argv(argv, stdin_text=expr.content)
        result.rendered = render_command(expr)
        result.metadata = {
            **(result.metadata or {}),
            "execution_target": self.name,
            "workflow": self.workflow_name,
            "container": self.container,
        }
        return result

    def _rejected(self, expr: CommandExpr, message: str) -> CommandResult:
        return CommandResult(
            success=False,
            exit_status=126,
            stdout="",
            stderr=message,
            duration_ms=0,
            rendered=render_command(expr),
            metadata={"execution_target": self.name, "sandbox_rejected": True},
        )

    def _rejected_message(self, message: str) -> CommandResult:
        return CommandResult(
            success=False,
            exit_status=126,
            stdout="",
            stderr=message,
            duration_ms=0,
            rendered="",
            metadata={"execution_target": self.name, "sandbox_rejected": True},
        )


def confine_work_path(path: str) -> str:
    """Lexically force a write_file path to stay under /work."""
    if not isinstance(path, str) or not path.strip() or "\0" in path:
        raise SandboxEscape("write_file path is empty or contains NUL.")
    raw = path if path.startswith("/") else f"{WORK_ROOT}/{path}"
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise SandboxEscape("write_file path cannot contain '..'.")
        parts.append(part)
    if not parts or parts[0] != "work":
        raise SandboxEscape("write_file only writes under /work inside the workflow container.")
    return "/" + "/".join(parts)
