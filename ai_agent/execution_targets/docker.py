from __future__ import annotations

from ai_agent.commands.ast import CommandExpr, SingleCommand, WriteFileCommand
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.commands.render import render_command
from ai_agent.docker_broker.authorize import BrokerRejected, authorize, plan_target_exec
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
        broker=None,
    ):
        self.name = name
        self.description = description
        self.container = container
        self.docker_bin = docker_bin
        self.user = user.strip()
        self._executor = executor
        self._broker = broker

    def display(self) -> str:
        if self.user:
            return f"{self.name} (docker:{self.container} as {self.user})"
        return f"{self.name} (docker:{self.container})"

    def docker_argv(self, expr: CommandExpr) -> list[str]:
        """Host argv. The container and user are the stored target, not the command."""
        if isinstance(expr, SingleCommand):
            return plan_target_exec(
                container=self.container,
                user=self.user,
                cwd=expr.cwd,
                argv=expr.argv,
                docker_bin=self.docker_bin,
            )
        return plan_target_exec(
            container=self.container,
            user=self.user,
            script=render_posix_script(expr),
            docker_bin=self.docker_bin,
        )

    def run(self, expr: CommandExpr) -> CommandResult:
        if isinstance(expr, WriteFileCommand):
            return self._rejected(expr, "write_file is only supported on target local")
        try:
            planned = self.docker_argv(expr)
            authorize(planned)
        except BrokerRejected as exc:
            return self._rejected(expr, str(exc))
        if self._broker is not None:
            try:
                if isinstance(expr, SingleCommand):
                    completed = self._broker.exec(
                        container=self.container,
                        user=self.user,
                        cwd=expr.cwd,
                        argv=list(expr.argv),
                        timeout=self._timeout(),
                    )
                else:
                    completed = self._broker.exec(
                        container=self.container,
                        user=self.user,
                        script=render_posix_script(expr),
                        timeout=self._timeout(),
                    )
            except BrokerRejected as exc:
                return self._rejected(expr, str(exc))
            return self._from_completed(expr, completed)
        result = self._executor.run(SingleCommand(argv=planned))
        result.rendered = render_command(expr)
        result.metadata = self._metadata()
        return result

    def _timeout(self) -> float:
        value = getattr(self._executor, "timeout", 120)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return 120
        return float(value)

    def _from_completed(self, expr: CommandExpr, completed) -> CommandResult:
        return CommandResult(
            success=completed.returncode == 0,
            exit_status=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_ms=0,
            rendered=render_command(expr),
            metadata=self._metadata(),
        )

    def _metadata(self) -> dict:
        return {
            "execution_target": self.name,
            "docker_user": self.user or "container-default",
        }

    def _rejected(self, expr: CommandExpr, message: str) -> CommandResult:
        return CommandResult(
            success=False,
            exit_status=126,
            stdout="",
            stderr=message,
            duration_ms=0,
            rendered=render_command(expr),
            metadata={**self._metadata(), "docker_rejected": True},
        )
