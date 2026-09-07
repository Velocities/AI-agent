import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_agent.agent.loop import AgentLoop
from ai_agent.agent.tools import COMMAND_DUMP_NUDGE, CONTINUE_NUDGE
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.llm.base import LLMErrorKind, LLMMessage, LLMResponse, ToolCall
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


def test_llm_unavailable_failure(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content=""),
        error="LLM endpoint is unavailable.",
        error_kind=LLMErrorKind.UNAVAILABLE,
    )
    result = agent.run("hello")
    assert result.error is not None
    assert "unavailable" in result.final_message


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


def test_dumped_command_json_is_nudged_to_use_the_tool(agent_parts) -> None:
    agent, llm, _ = agent_parts
    dumped = (
        '{"type":"redirect","cmd":{"type":"single","argv":["echo","hi"]},'
        '"op":">","path":"/tmp/test.txt"}'
    )
    llm.chat.side_effect = [
        LLMResponse(message=LLMMessage(role="assistant", content=dumped)),
        LLMResponse(message=LLMMessage(role="assistant", content="Will use the tool.")),
    ]
    result = agent.run("write a file on home-server")
    assert result.final_message == "Will use the tool."
    assert llm.chat.call_count == 2
    assert agent.messages[-2].content == COMMAND_DUMP_NUDGE


def test_plain_text_is_the_final_answer(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content="Plain text answer.")
    )
    result = agent.run("hello")
    assert result.final_message == "Plain text answer."
    assert result.error is None
    assert llm.chat.call_count == 1


def test_agent_resumes_after_length_limit(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(role="assistant", content="Errors happen when a value"),
            stop_reason="length",
        ),
        LLMResponse(
            message=LLMMessage(role="assistant", content=" is missing."),
        ),
    ]

    result = agent.run("explain something long")

    assert result.final_message == "Errors happen when a value is missing."
    assert result.error is None
    assert llm.chat.call_count == 2
    assert result.iterations == 1


def test_agent_resume_prompt_stays_bounded(agent_parts) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_continuation_tail = 20
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(role="assistant", content="x" * 500),
            stop_reason="length",
        ),
        LLMResponse(message=LLMMessage(role="assistant", content="done.")),
    ]

    agent.run("explain something long")

    resume_messages = llm.chat.call_args_list[1][0][0]
    assert resume_messages[-1].content == CONTINUE_NUDGE
    assert resume_messages[-2].role == "assistant"
    assert resume_messages[-2].content == "x" * 20
    # The partial answer is not committed to history until the turn completes.
    assert len(resume_messages) == len(agent.messages) + 1


def test_agent_resume_drops_repeated_text(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="Common mistakes include catching overly broad",
            ),
            stop_reason="length",
        ),
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content=(
                    "# Continuing\n\nCommon mistakes include catching overly broad "
                    "exceptions."
                ),
            ),
        ),
    ]

    result = agent.run("explain error handling")

    assert result.final_message == (
        "Common mistakes include catching overly broad exceptions."
    )


def test_agent_resumes_after_recoverable_stream_error(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(role="assistant", content="Errors happen when a value"),
            error="LLM stream was interrupted.",
            error_kind=LLMErrorKind.STREAM_INTERRUPTED,
        ),
        LLMResponse(
            message=LLMMessage(role="assistant", content=" is missing."),
        ),
    ]

    result = agent.run("explain something long")

    assert result.final_message == "Errors happen when a value is missing."
    assert result.error is None
    assert llm.chat.call_count == 2


def test_agent_keeps_partial_answer_when_resume_fails_hard(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(role="assistant", content="Errors happen when a value"),
            stop_reason="length",
        ),
        LLMResponse(
            message=LLMMessage(role="assistant", content=""),
            error="LLM endpoint is unavailable.",
            error_kind=LLMErrorKind.UNAVAILABLE,
        ),
    ]

    result = agent.run("explain something long")

    assert result.final_message == "Errors happen when a value"
    assert result.error == "LLM endpoint is unavailable."


def test_agent_reports_truncation_after_repeated_stream_interruptions(
    agent_parts,
) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_max_continuations = 1
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content="chunk "),
        error="LLM stream was interrupted.",
        error_kind=LLMErrorKind.STREAM_INTERRUPTED,
    )

    result = agent.run("explain something endless")

    assert result.error == "truncated"
    assert result.final_message == "chunk chunk"


def test_agent_stops_after_continuation_budget(agent_parts) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_max_continuations = 2
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content="chunk "),
        stop_reason="length",
    )

    result = agent.run("explain something endless")

    assert result.error == "truncated"
    assert result.final_message == "chunk chunk chunk"
    assert llm.chat.call_count == 3


def test_unrecoverable_llm_error_still_fails(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content=""),
        error="LLM endpoint is unavailable.",
        error_kind=LLMErrorKind.UNAVAILABLE,
    )

    result = agent.run("hello")

    assert result.error == "LLM endpoint is unavailable."
    assert result.error_kind == LLMErrorKind.UNAVAILABLE
    assert llm.chat.call_count == 1


def test_empty_response_retries_then_fails(agent_parts) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_max_iterations = 2
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content="   ")
    )
    result = agent.run("hello")
    assert result.error == "empty_response"
    assert llm.chat.call_count == 2


def test_warmup_uses_system_prompt_and_tools(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content="", tool_calls=[])
    )

    ok, detail, duration = agent.warmup()

    assert ok is True
    assert detail == "ready"
    assert duration >= 0
    llm.chat.assert_called_once()
    messages, kwargs = llm.chat.call_args
    assert messages[0][0].role == "system"
    assert kwargs.get("tools") is not None
    assert len(agent.messages) == 1


def test_warmup_failure(agent_parts) -> None:
    agent, llm, _ = agent_parts
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content=""),
        error="Ollama is unavailable.",
    )

    ok, detail, _duration = agent.warmup()

    assert ok is False
    assert "Ollama" in detail
