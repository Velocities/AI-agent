from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ai_agent.commands.ast import CommandExpr
from ai_agent.commands.executor import CommandResult


class UnknownExecutionTarget(KeyError):
    """The model or caller asked for a name that is not in configuration."""


@dataclass(frozen=True)
class TargetSummary:
    name: str
    kind: str
    description: str
    display: str


class ExecutionTarget(ABC):
    """Where an approved CommandExpr actually runs."""

    name: str
    kind: str
    description: str

    def display(self) -> str:
        return f"{self.name} ({self.kind})"

    def summary(self) -> TargetSummary:
        return TargetSummary(
            name=self.name,
            kind=self.kind,
            description=self.description,
            display=self.display(),
        )

    @abstractmethod
    def run(self, expr: CommandExpr) -> CommandResult:
        raise NotImplementedError
