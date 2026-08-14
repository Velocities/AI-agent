import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_agent.agent.loop import AgentLoop
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.llm.base import LLMMessage, LLMResponse, ToolCall
from ai_agent.policy.engine import PolicyEngine


@pytest.fixture
def agent_parts(tmp_path: Path):
    settings = Settings()
    settings.agent_max_iterations = 3
    policy = PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")
    executor = CommandExecutor(
        timeout=5,
        output_limit=1024,
        scratch_dir=tmp_path / "scratch",
    )
    audit_log = tmp_path / "audit.jsonl"
    audit = AuditLogger(log_path=audit_log, user="test")
    session = ApprovalSession()
    console = MagicMock()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, console)
    prompter.should_auto_run = MagicMock(return_value=True)
    llm = MagicMock()
    agent = AgentLoop(
        settings=settings,
        llm=llm,
        policy=policy,
        executor=executor,
        audit=audit,
        prompter=prompter,
        session=session,
    )
    return agent, llm, audit_log


def test_max_iterations(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="1",
                    name="run_command",
                    arguments={
                        "reason": "inspect",
                        "command": {"type": "single", "argv": ["df", "-h"]},
                    },
                )
            ],
        )
    )
    result = agent.run("check disk")
    assert result.error == "max_iterations"
    assert result.iterations == 3


def test_ollama_failure(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content=""),
        error="Ollama is unavailable. Check OLLAMA_HOST.",
    )
    result = agent.run("hello")
    assert result.error is not None
    assert "Ollama" in result.final_message


def test_audit_log_written(agent_parts) -> None:
    agent, llm, audit_log = agent_parts
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="run_command",
                        arguments={
                            "reason": "inspect",
                            "command": {"type": "single", "argv": ["docker", "ps"]},
                        },
                    )
                ],
            )
        ),
        LLMResponse(
            message=LLMMessage(role="assistant", content="Docker is running.")
        ),
    ]
    agent.run("show docker")
    lines = audit_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["tool_name"] == "run_command"
    assert record["confirmation_granted"] is True


def test_policy_denial_is_audited(agent_parts) -> None:
    agent, llm, audit_log = agent_parts
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="run_command",
                        arguments={
                            "reason": "bad",
                            "command": {"type": "single", "argv": ["rm", "-rf", "/"]},
                        },
                    )
                ],
            )
        ),
        LLMResponse(
            message=LLMMessage(role="assistant", content="I cannot do that.")
        ),
    ]
    agent.run("delete everything")
    record = json.loads(audit_log.read_text(encoding="utf-8").strip())
    assert record["allowed"] is False
    assert record["success"] is False
