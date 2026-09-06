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
    ):
        self.name = name
        self.description = description
        self.container = container
        self.docker_bin = docker_bin
        self._executor = executor

    def display(self) -> str:
        return f"{self.name} (docker:{self.container})"

    def docker_argv(self, expr: CommandExpr) -> list[str]:
        if isinstance(expr, SingleCommand):
            argv = [self.docker_bin, "exec", "-i"]
            if expr.cwd:
                argv.extend(["-w", expr.cwd])
            argv.append(self.container)
            argv.extend(expr.argv)
            return argv
        return [
            self.docker_bin,
            "exec",
            "-i",
            self.container,
            "/bin/sh",
            "-c",
            render_posix_script(expr),
        ]

    def run(self, expr: CommandExpr) -> CommandResult:
        result = self._executor.run(SingleCommand(argv=self.docker_argv(expr)))
        result.rendered = render_command(expr)
        result.metadata = {**(result.metadata or {}), "execution_target": self.name}
        return result
