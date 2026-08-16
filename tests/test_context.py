import getpass
import platform
import socket

from ai_agent.agent.context import (
    RuntimeContext,
    build_system_prompt,
    gather_runtime_context,
    platform_guidance,
)
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
    )
    prompt = build_system_prompt(context, ["docker", "cat", "grep"])
    assert "Windows" in prompt
    assert r"C:\Users\Admin\Desktop\Repos\AI-agent" in prompt
    assert "run_command" in prompt
    assert "run_commands" in prompt
    assert "respond" in prompt
    assert "finished" in prompt
    assert "docker, cat, grep" in prompt
    assert "Do NOT assume Ubuntu" in prompt
    assert "use tools first" in prompt.lower()


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
    )
    guidance = platform_guidance(context)
    assert "Linux" in guidance
    assert "systemctl" in guidance


def test_gather_runtime_context_uses_current_environment() -> None:
    context = gather_runtime_context(Settings())
    assert context.os_name == platform.system()
    assert context.hostname == socket.gethostname()
    assert context.username == getpass.getuser()
