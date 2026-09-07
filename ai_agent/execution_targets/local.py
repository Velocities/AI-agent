from __future__ import annotations

from ai_agent.commands.ast import CommandExpr
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.execution_targets.base import ExecutionTarget


class LocalExecutionTarget(ExecutionTarget):
    kind = "local"

    def __init__(
        self,
        executor: CommandExecutor,
        *,
        name: str = "local",
        description: str = "This machine (where the agent CLI runs)",
    ):
        self.name = name
        self.description = description
        self._executor = executor

    def display(self) -> str:
        return f"{self.name} (this machine)"

    def run(self, expr: CommandExpr) -> CommandResult:
        result = self._executor.run(expr)
        result.metadata = {**(result.metadata or {}), "execution_target": self.name}
        return result
