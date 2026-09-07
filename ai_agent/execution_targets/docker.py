from __future__ import annotations

from ai_agent.commands.ast import CommandExpr, SingleCommand
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.commands.render import render_command
from ai_agent.execution_targets.base import ExecutionTarget
from ai_agent.execution_targets.remote_script import render_posix_script


class DockerExecutionTarget(ExecutionTarget):
    kind = "docker"

    def __init__(
        self,
        *,
        name: str,
        container: str,
        executor: CommandExecutor,
        description: str = "",
        docker_bin: str = "docker",
        user: str = "",
    ):
        self.name = name
        self.description = description
        self.container = container
        self.docker_bin = docker_bin
        self.user = user.strip()
        self._executor = executor

    def display(self) -> str:
        if self.user:
            return f"{self.name} (docker:{self.container} as {self.user})"
        return f"{self.name} (docker:{self.container})"

    def _exec_prefix(self, *, cwd: str | None = None) -> list[str]:
        argv = [self.docker_bin, "exec", "-i"]
        if self.user:
            argv.extend(["-u", self.user])
        if cwd:
            argv.extend(["-w", cwd])
        argv.append(self.container)
        return argv

    def docker_argv(self, expr: CommandExpr) -> list[str]:
        if isinstance(expr, SingleCommand):
            return [*self._exec_prefix(cwd=expr.cwd), *expr.argv]
        return [
            *self._exec_prefix(),
            "/bin/sh",
            "-c",
            render_posix_script(expr),
        ]

    def run(self, expr: CommandExpr) -> CommandResult:
        result = self._executor.run(SingleCommand(argv=self.docker_argv(expr)))
        result.rendered = render_command(expr)
        result.metadata = {
            **(result.metadata or {}),
            "execution_target": self.name,
            "docker_user": self.user or "container-default",
        }
        return result
