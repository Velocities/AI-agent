"""Workflow sandbox commands skip host policy and approval."""

from ai_agent.agent.tool_handler import ToolHandler
from ai_agent.commands.ast import SingleCommand
from ai_agent.execution_targets.sandbox import SandboxExecutionTarget


def test_sandbox_target_opted_out_of_host_policy() -> None:
    target = SandboxExecutionTarget(
        container="demo",
        executor=None,  # type: ignore[arg-type]
        workflow_name="text-lab",
    )
    assert target.uses_host_policy is False


def test_sandbox_policy_decision_always_allows() -> None:
    expr = SingleCommand(argv=["fetch-pages"])
    decision = ToolHandler._sandbox_policy_decision(expr)
    assert decision.allowed
    assert "isolated container" in decision.reason