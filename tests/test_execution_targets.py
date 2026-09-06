from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from ai_agent.agent.loop import AgentLoop
from ai_agent.agent.tools import build_tool_definitions
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.ast import parse_command_expr
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.config import Settings
from ai_agent.execution_targets.base import UnknownExecutionTarget
from ai_agent.execution_targets.docker import DockerExecutionTarget
from ai_agent.execution_targets.local import LocalExecutionTarget
from ai_agent.execution_targets.remote_script import posix_quote, render_posix_script
from ai_agent.execution_targets.router import ExecutionTargetRouter, load_router
from ai_agent.execution_targets.ssh import SshExecutionTarget
from ai_agent.execution_targets.store import TargetConfigError, load_targets_file
from ai_agent.llm.base import LLMMessage, LLMResponse, ToolCall
from ai_agent.policy.engine import PolicyEngine


def _fake_executor(captured: list[list[str]] | None = None) -> CommandExecutor:
    executor = MagicMock(spec=CommandExecutor)

    def run(expr):
        if captured is not None:
            captured.append(list(expr.argv))
        return CommandResult(
            success=True,
            exit_status=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            rendered="wrapped",
        )

    executor.run.side_effect = run
    return executor


def test_posix_quote_neutralizes_metacharacters() -> None:
    quoted = posix_quote("ps; rm -rf /")
    assert quoted == "'ps; rm -rf /'"
    script = render_posix_script(
        parse_command_expr({"type": "single", "argv": ["docker", "ps; evil"]})
    )
    assert "ps; evil" in script
    assert script == "docker 'ps; evil'" or script.endswith("'ps; evil'")


def test_posix_script_builds_pipe_and_and() -> None:
    expr = parse_command_expr(
        {
            "type": "and",
            "left": {
                "type": "pipe",
                "left": {"type": "single", "argv": ["journalctl", "-u", "nginx"]},
                "right": ["grep", "error"],
            },
            "right": {"type": "single", "argv": ["systemctl", "restart", "nginx"]},
        }
    )
    script = render_posix_script(expr)
    assert "|" in script
    assert "&&" in script
    assert posix_quote("journalctl") in script or "'journalctl'" in script


def test_posix_redirect_creates_parent_dir() -> None:
    expr = parse_command_expr(
        {
            "type": "redirect",
            "cmd": {"type": "single", "argv": ["echo", "hello from agent"]},
            "op": ">",
            "path": "/tmp/ai-agent/testfile.txt",
        }
    )
    script = render_posix_script(expr)
    assert "mkdir -p '/tmp/ai-agent'" in script
    assert ">" in script
    assert "/tmp/ai-agent/testfile.txt" in script


def test_ssh_target_uses_quoted_script_not_raw_argv(tmp_path: Path) -> None:
    captured: list[list[str]] = []
    identity = tmp_path / "id_ed25519"
    identity.write_text("dummy", encoding="utf-8")
    target = SshExecutionTarget(
        name="home-server",
        host="192.168.1.10",
        user="ai",
        port=22,
        identity_file=identity,
        known_hosts=tmp_path / "known_hosts",
        executor=_fake_executor(captured),
    )
    expr = parse_command_expr(
        {"type": "single", "argv": ["systemctl", "status", "nginx; reboot"]}
    )
    result = target.run(expr)
    assert result.success
    assert "nginx" in result.rendered
    argv = captured[0]
    assert argv[0] == "ssh"
    assert argv[-2] == "--"
    assert "nginx; reboot" in argv[-1]
    assert argv[-1] != "nginx; reboot"
    assert result.metadata["execution_target"] == "home-server"


def test_docker_target_execs_single_without_shell() -> None:
    captured: list[list[str]] = []
    target = DockerExecutionTarget(
        name="web",
        container="nginx",
        executor=_fake_executor(captured),
    )
    expr = parse_command_expr({"type": "single", "argv": ["nginx", "-t"]})
    result = target.run(expr)
    assert captured[0] == ["docker", "exec", "-i", "nginx", "nginx", "-t"]
    assert result.metadata["execution_target"] == "web"


def test_docker_target_uses_sh_c_for_pipes() -> None:
    captured: list[list[str]] = []
    target = DockerExecutionTarget(
        name="web",
        container="nginx",
        executor=_fake_executor(captured),
    )
    expr = parse_command_expr(
        {
            "type": "pipe",
            "left": {"type": "single", "argv": ["cat", "/var/log/nginx/error.log"]},
            "right": ["grep", "error"],
        }
    )
    target.run(expr)
    assert captured[0][:6] == ["docker", "exec", "-i", "nginx", "/bin/sh", "-c"]
    assert "|" in captured[0][-1]


def test_router_unknown_name() -> None:
    executor = CommandExecutor(timeout=1, output_limit=16, scratch_dir=Path("."))
    router = ExecutionTargetRouter.local_only(executor)
    with pytest.raises(UnknownExecutionTarget):
        router.resolve("192.168.1.10")


def test_load_yaml_and_router(tmp_path: Path) -> None:
    identity = tmp_path / "id_ed25519"
    identity.write_text("key", encoding="utf-8")
    known = tmp_path / "known_hosts"
    known.write_text("", encoding="utf-8")
    path = tmp_path / "execution_targets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "default_target": "local",
                "execution_targets": {
                    "local": {"type": "local", "description": "here"},
                    "home-server": {
                        "type": "ssh",
                        "host": "192.168.1.10",
                        "user": "ai",
                        "identity_file": str(identity),
                        "known_hosts": str(known),
                    },
                    "web": {"type": "docker", "container": "nginx"},
                },
            }
        ),
        encoding="utf-8",
    )
    executor = CommandExecutor(timeout=1, output_limit=16, scratch_dir=tmp_path)
    router = load_router(executor, path)
    assert set(router.names()) == {"local", "home-server", "web"}
    assert isinstance(router.resolve("local"), LocalExecutionTarget)
    assert router.resolve("home-server").display().startswith("home-server (ssh://")
    assert router.resolve("web").display() == "web (docker:nginx)"


def test_file_default_target_is_honored(tmp_path: Path) -> None:
    identity = tmp_path / "id_ed25519"
    identity.write_text("key", encoding="utf-8")
    known = tmp_path / "known_hosts"
    known.write_text("", encoding="utf-8")
    path = tmp_path / "execution_targets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "default_target": "home-server",
                "execution_targets": {
                    "local": {"type": "local"},
                    "home-server": {
                        "type": "ssh",
                        "host": "192.168.1.10",
                        "user": "ai",
                        "identity_file": str(identity),
                        "known_hosts": str(known),
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    executor = CommandExecutor(timeout=1, output_limit=16, scratch_dir=tmp_path)
    router = load_router(executor, path)
    assert router.default_name == "home-server"
    overridden = load_router(executor, path, default_override="local")
    assert overridden.default_name == "local"


def test_rejects_local_name_for_ssh(tmp_path: Path) -> None:
    path = tmp_path / "execution_targets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "execution_targets": {
                    "local": {
                        "type": "ssh",
                        "host": "1.2.3.4",
                        "user": "ai",
                        "identity_file": "key",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TargetConfigError):
        load_targets_file(path)


def test_missing_file_is_local_only(tmp_path: Path) -> None:
    document = load_targets_file(tmp_path / "missing.yaml")
    assert list(document.execution_targets) == ["local"]


def test_tool_schema_enum_is_configured_names() -> None:
    tools = build_tool_definitions(["local", "home-server"])
    run_command = tools[0]["function"]["parameters"]["properties"]["target"]
    assert run_command["enum"] == ["local", "home-server"]
    assert "required" not in run_command or "target" not in tools[0]["function"]["parameters"]["required"]


def test_agent_omitted_target_runs_local(tmp_path: Path) -> None:
    settings = Settings()
    settings.agent_max_iterations = 2
    policy = PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")
    captured: list[list[str]] = []
    executor = _fake_executor(captured)
    router = ExecutionTargetRouter.local_only(executor)
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
                            "reason": "inspect",
                            "command": {"type": "single", "argv": ["docker", "ps"]},
                        },
                    )
                ],
            )
        ),
        LLMResponse(message=LLMMessage(role="assistant", content="done")),
    ]
    session = ApprovalSession()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, MagicMock())
    prompter.should_auto_run = MagicMock(return_value=True)
    agent = AgentLoop(
        settings=settings,
        llm=llm,
        policy=policy,
        executor=executor,
        audit=AuditLogger(log_path=tmp_path / "audit.jsonl", user="test"),
        prompter=prompter,
        session=session,
        router=router,
    )
    result = agent.run("show docker")
    assert result.final_message == "done"
    assert captured
    assert captured[0] == ["docker", "ps"]


def test_agent_rejects_invented_target(tmp_path: Path) -> None:
    settings = Settings()
    settings.agent_max_iterations = 2
    policy = PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")
    captured: list[list[str]] = []
    executor = _fake_executor(captured)
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
                            "target": "evil-box",
                            "reason": "hack",
                            "command": {"type": "single", "argv": ["docker", "ps"]},
                        },
                    )
                ],
            )
        ),
        LLMResponse(message=LLMMessage(role="assistant", content="blocked")),
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
        router=ExecutionTargetRouter.local_only(executor),
    )
    result = agent.run("pwn")
    assert result.final_message == "blocked"
    assert captured == []
    tool_msg = agent.messages[-2]
    assert "Unknown execution target" in tool_msg.content
