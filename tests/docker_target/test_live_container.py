from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_agent.agent.loop import AgentLoop
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.ast import parse_command_expr
from ai_agent.config import Settings
from ai_agent.execution_targets.router import ExecutionTargetRouter
from ai_agent.llm.base import LLMMessage, LLMResponse, ToolCall
from ai_agent.policy.engine import PolicyEngine

from tests.docker_target.conftest import DOCKERFILE_DIR

pytestmark = pytest.mark.docker


def test_unprivileged_user_inside_container(docker_target) -> None:
    result = docker_target.run(
        parse_command_expr({"type": "single", "argv": ["whoami"]})
    )
    assert result.success, result.stderr
    assert result.stdout.strip() == "agent"


def test_writes_scratch_file_via_redirect(docker_target) -> None:
    write = docker_target.run(
        parse_command_expr(
            {
                "type": "redirect",
                "cmd": {
                    "type": "single",
                    "argv": ["echo", "hello from docker target"],
                },
                "op": ">",
                "path": "/tmp/ai-agent/hello.txt",
            }
        )
    )
    assert write.success, write.stderr

    read = docker_target.run(
        parse_command_expr(
            {"type": "single", "argv": ["cat", "/tmp/ai-agent/hello.txt"]}
        )
    )
    assert read.success, read.stderr
    assert "hello from docker target" in read.stdout
    assert read.metadata["execution_target"] == "lab"


def test_exec_as_root_does_not_need_sudo_in_existing_container(
    docker_root_target,
) -> None:
    """Real-world path: image USER is unprivileged; target sets user=root."""
    who = docker_root_target.run(
        parse_command_expr({"type": "single", "argv": ["whoami"]})
    )
    assert who.success, who.stderr
    assert who.stdout.strip() == "root"

    write = docker_root_target.run(
        parse_command_expr(
            {"type": "single", "argv": ["touch", "/root/via-exec-u.txt"]}
        )
    )
    assert write.success, write.stderr
    read = docker_root_target.run(
        parse_command_expr(
            {"type": "single", "argv": ["cat", "/root/via-exec-u.txt"]}
        )
    )
    assert read.success, read.stderr
    assert read.metadata["docker_user"] == "root"


def test_passwordless_sudo_is_root_without_prompt(docker_target) -> None:
    """sudo -n fails immediately if a password would be required."""
    result = docker_target.run(
        parse_command_expr({"type": "single", "argv": ["sudo", "-n", "whoami"]})
    )
    assert result.success, result.stderr
    assert result.stdout.strip() == "root"
    assert "password" not in result.stderr.lower()


def test_sudo_can_write_under_root(docker_target) -> None:
    write = docker_target.run(
        parse_command_expr(
            {
                "type": "single",
                "argv": ["sudo", "-n", "touch", "/root/from-agent.txt"],
            }
        )
    )
    assert write.success, write.stderr

    read = docker_target.run(
        parse_command_expr(
            {
                "type": "single",
                "argv": ["sudo", "-n", "cat", "/root/from-agent.txt"],
            }
        )
    )
    assert read.success, read.stderr


def test_agent_loop_writes_file_on_docker_target(
    docker_target, executor, tmp_path: Path
) -> None:
    settings = Settings()
    settings.agent_max_iterations = 3
    policy = PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")
    llm = MagicMock()
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
                            "target": "lab",
                            "reason": "write a test file in the container",
                            "command": {
                                "type": "redirect",
                                "cmd": {
                                    "type": "single",
                                    "argv": ["echo", "via agent loop"],
                                },
                                "op": ">",
                                "path": "/tmp/ai-agent/loop.txt",
                            },
                        },
                    )
                ],
            )
        ),
        LLMResponse(message=LLMMessage(role="assistant", content="Wrote the file.")),
    ]
    session = ApprovalSession()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, MagicMock())
    prompter.should_auto_run = MagicMock(return_value=True)
    agent = AgentLoop(
        settings=settings,
        llm=llm,
        policy=policy,
        executor=executor,
        audit=AuditLogger(user="test"),
        prompter=prompter,
        session=session,
        router=ExecutionTargetRouter(
            {"lab": docker_target},
            default_name="lab",
        ),
    )

    result = agent.run("write a file on the lab container")
    assert result.final_message == "Wrote the file."

    read = docker_target.run(
        parse_command_expr(
            {"type": "single", "argv": ["cat", "/tmp/ai-agent/loop.txt"]}
        )
    )
    assert read.success, read.stderr
    assert "via agent loop" in read.stdout


def test_agent_loop_sudo_with_container_admin_policy(
    docker_target, executor, tmp_path: Path
) -> None:
    settings = Settings()
    settings.agent_max_iterations = 3
    policy = PolicyEngine.from_yaml(
        DOCKERFILE_DIR / "container_admin_policy.yaml",
        tmp_path / "scratch",
    )
    llm = MagicMock()
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
                            "target": "lab",
                            "reason": "prove passwordless root inside the container",
                            "command": {
                                "type": "single",
                                "argv": ["sudo", "-n", "whoami"],
                            },
                        },
                    )
                ],
            )
        ),
        LLMResponse(message=LLMMessage(role="assistant", content="root inside lab")),
    ]
    session = ApprovalSession()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, MagicMock())
    prompter.should_auto_run = MagicMock(return_value=True)
    agent = AgentLoop(
        settings=settings,
        llm=llm,
        policy=policy,
        executor=executor,
        audit=AuditLogger(user="test"),
        prompter=prompter,
        session=session,
        router=ExecutionTargetRouter({"lab": docker_target}, default_name="lab"),
    )

    result = agent.run("are we root in the container with sudo?")
    assert result.final_message == "root inside lab"
    tool_payload = agent.messages[-2].content
    assert '"success": true' in tool_payload
    assert "root" in tool_payload
