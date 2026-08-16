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
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="respond",
                        arguments={"message": "Docker is running.", "finished": True},
                    )
                ],
            )
        ),
    ]
    result = agent.run("show docker")
    assert result.final_message == "Docker is running."
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
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="respond",
                        arguments={"message": "I cannot do that.", "finished": True},
                    )
                ],
            )
        ),
    ]
    agent.run("delete everything")
    record = json.loads(audit_log.read_text(encoding="utf-8").strip())
    assert record["allowed"] is False
    assert record["success"] is False


def test_respond_finished_true_ends_turn(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="1",
                    name="respond",
                    arguments={"message": "All done.", "finished": True},
                )
            ],
        )
    )
    result = agent.run("hello")
    assert result.final_message == "All done."
    assert llm.chat.call_count == 1


def test_respond_finished_false_continues(agent_parts) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_max_iterations = 5
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="respond",
                        arguments={"message": "Still working.", "finished": False},
                    )
                ],
            )
        ),
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="respond",
                        arguments={"message": "Complete answer.", "finished": True},
                    )
                ],
            )
        ),
    ]
    result = agent.run("explain something")
    assert result.final_message == "Complete answer."
    assert llm.chat.call_count == 2


def test_plain_text_without_respond_retries_then_fails(agent_parts) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_max_iterations = 2
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content="Plain text only.")
    )
    result = agent.run("hello")
    assert result.error == "missing_respond"
    assert llm.chat.call_count == 2
