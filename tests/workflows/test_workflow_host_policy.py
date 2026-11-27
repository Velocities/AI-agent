"""Workflow containers skip host policy and approval."""

from ai_agent.agent.command_parse import workflow_policy_decision
from ai_agent.commands.ast import SingleCommand
from ai_agent.execution_targets.workflow import WorkflowExecutionTarget


def test_workflow_target_opted_out_of_host_policy() -> None:
    target = WorkflowExecutionTarget(
        container="demo",
        executor=None,  # type: ignore[arg-type]
        workflow_name="text-lab",
    )
    assert target.uses_host_policy is False


def test_workflow_policy_decision_always_allows() -> None:
    expr = SingleCommand(argv=["fetch-pages"])
    decision = workflow_policy_decision(expr)
    assert decision.allowed
    assert "isolated container" in decision.reason