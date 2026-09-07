from __future__ import annotations

from pathlib import Path

from ai_agent.commands.ast import CommandExpr, SingleCommand
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.commands.render import render_command
from ai_agent.execution_targets.base import ExecutionTarget
from ai_agent.execution_targets.remote_script import render_posix_script
from ai_agent.llm.ssh_sandbox import ssh_path_for_config


class SshExecutionTarget(ExecutionTarget):
    kind = "ssh"

    def __init__(
        self,
        *,
        name: str,
        host: str,
        user: str,
        port: int,
        identity_file: Path,
        known_hosts: Path,
        executor: CommandExecutor,
        description: str = "",
        ssh_bin: str = "ssh",
    ):
        self.name = name
        self.description = description
        self.host = host
        self.user = user
        self.port = port
        self.identity_file = identity_file
        self.known_hosts = known_hosts
        self._executor = executor
        self.ssh_bin = ssh_bin

    def display(self) -> str:
        dest = f"ssh://{self.user}@{self.host}"
        if self.port != 22:
            dest += f":{self.port}"
        return f"{self.name} ({dest})"

    def ssh_argv(self, expr: CommandExpr) -> list[str]:
        script = render_posix_script(expr)
        return [
            self.ssh_bin,
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={ssh_path_for_config(self.known_hosts)}",
            "-o",
            f"IdentityFile={ssh_path_for_config(self.identity_file)}",
            "-o",
            "ClearAllForwardings=yes",
            "-p",
            str(self.port),
            "-l",
            self.user,
            self.host,
            "--",
            script,
        ]

    def run(self, expr: CommandExpr) -> CommandResult:
        if not self.identity_file.is_file():
            return CommandResult(
                success=False,
                exit_status=127,
                stdout="",
                stderr=(
                    f"SSH identity for target {self.name!r} is missing: "
                    f"{self.identity_file}. Run: ai-agent config execution-target"
                ),
                duration_ms=0,
                rendered=render_command(expr),
                metadata={"execution_target": self.name},
            )
        result = self._executor.run(SingleCommand(argv=self.ssh_argv(expr)))
        result.rendered = render_command(expr)
        result.metadata = {**(result.metadata or {}), "execution_target": self.name}
        return result
