import getpass
import platform
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_agent.agent.context import (
    RuntimeContext,
    build_system_prompt,
    gather_runtime_context,
    platform_guidance,
    resolve_local_command_identity,
)
from ai_agent.commands.run_as import PosixAccount, build_command_executor
from ai_agent.config import Settings


def test_system_prompt_includes_runtime_platform() -> None:
    context = RuntimeContext(
        os_name="Windows",
        os_release="10",
        os_version="10.0.19045",
        hostname="DESKTOP-TEST",
        username="Admin",
        cwd=r"C:\Users\Admin\Desktop\Repos\AI-agent",
        home=r"C:\Users\Admin",
        scratch_dir=r"C:\Users\Admin\AppData\Local\Temp\ai-agent",
        confirmation_mode="balanced",
        is_windows=True,
        is_linux=False,
        local_command_user="Admin",
        local_command_home=r"C:\Users\Admin",
    )
    prompt = build_system_prompt(context, ["docker", "cat", "grep"])
    assert "Windows" in prompt
    assert r"C:\Users\Admin\Desktop\Repos\AI-agent" in prompt
    assert "Local target commands run as: Admin" in prompt
    assert "run_command" in prompt
    assert "run_commands" in prompt
    assert "respond" in prompt
    assert "finished" in prompt
    assert "docker, cat, grep" in prompt
    assert "Do NOT assume Ubuntu" in prompt
    assert "use tools first" in prompt.lower()
    assert "omit target" in prompt
    assert "local (this machine)" in prompt
    assert "never invent a hostname" in prompt.lower()
    assert "Never call the ssh binary" in prompt
    assert "never print them" in prompt.lower() or "MUST call" in prompt


def test_platform_guidance_linux() -> None:
    context = RuntimeContext(
        os_name="Linux",
        os_release="6.8.0",
        os_version="#1 SMP",
        hostname="server",
        username="ai",
        cwd="/home/ai",
        home="/home/ai",
        scratch_dir="/tmp/ai-agent",
        confirmation_mode="balanced",
        is_windows=False,
        is_linux=True,
        local_command_user="velocities",
        local_command_home="/home/velocities",
    )
    guidance = platform_guidance(context)
    assert "Linux" in guidance
    assert "systemctl" in guidance
    assert "local" in guidance
    assert "velocities" in guidance
    assert "/home/velocities" in guidance


def test_platform_guidance_windows_includes_command_identity() -> None:
    context = RuntimeContext(
        os_name="Windows",
        os_release="10",
        os_version="",
        hostname="pc",
        username="Alice",
        cwd=r"C:\Users\Alice",
        home=r"C:\Users\Alice",
        scratch_dir=r"C:\Temp\ai-agent",
        confirmation_mode="balanced",
        is_windows=True,
        is_linux=False,
        local_command_user="Alice",
        local_command_home=r"C:\Users\Alice",
    )
    guidance = platform_guidance(context)
    assert "Alice" in guidance
    assert r"C:\Users\Alice" in guidance


def test_gather_runtime_context_uses_current_environment() -> None:
    context = gather_runtime_context(Settings())
    assert context.os_name == platform.system()
    assert context.hostname == socket.gethostname()
    assert context.username == getpass.getuser()
    assert context.local_command_user == getpass.getuser()
    assert context.local_command_home == str(Path.home())


def test_resolve_local_command_identity_defaults_to_process_user() -> None:
    user, home = resolve_local_command_identity(linux_username=None)
    assert user == getpass.getuser()
    assert home == str(Path.home())


def test_resolve_local_command_identity_on_windows_ignores_linux_username() -> None:
    with patch("ai_agent.agent.context.platform.system", return_value="Windows"):
        user, home = resolve_local_command_identity(linux_username="deployuser")
    assert user == getpass.getuser()
    assert home == str(Path.home())


def test_resolve_local_command_identity_linux_uses_run_as_account() -> None:
    with patch("ai_agent.agent.context.platform.system", return_value="Linux"):
        with patch(
            "ai_agent.commands.run_as.lookup_posix_account",
            return_value=PosixAccount(
                name="deployuser",
                uid=1001,
                gid=1001,
                home="/home/deployuser",
            ),
        ) as lookup:
            user, home = resolve_local_command_identity(linux_username="deployuser")
    lookup.assert_called_once_with("deployuser")
    assert user == "deployuser"
    assert home == "/home/deployuser"


def test_gather_runtime_context_linux_run_as(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_agent.agent.context.platform.system",
        lambda: "Linux",
    )
    with patch(
        "ai_agent.commands.run_as.lookup_posix_account",
        return_value=PosixAccount(
            name="deployuser",
            uid=1001,
            gid=1001,
            home="/home/deployuser",
        ),
    ):
        context = gather_runtime_context(Settings(), linux_username="deployuser")
    assert context.local_command_user == "deployuser"
    assert context.local_command_home == "/home/deployuser"


def test_build_command_executor_non_posix_uses_plain_executor(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_agent.commands.run_as.os.name", "nt")
    executor = build_command_executor(
        timeout=5,
        output_limit=1024,
        scratch_dir=tmp_path,
        linux_username="deployuser",
    )
    assert type(executor).__name__ == "CommandExecutor"


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux run-as integration")
def test_build_command_executor_linux_uses_run_as(tmp_path) -> None:
    executor = build_command_executor(
        timeout=5,
        output_limit=1024,
        scratch_dir=tmp_path,
        linux_username="nobody",
    )
    assert type(executor).__name__ == "RunAsCommandExecutor"
