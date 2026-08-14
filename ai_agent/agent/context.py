from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from getpass import getuser
from pathlib import Path

from ai_agent.config import Settings


@dataclass(frozen=True)
class RuntimeContext:
    os_name: str
    os_release: str
    os_version: str
    hostname: str
    username: str
    cwd: str
    home: str
    scratch_dir: str
    confirmation_mode: str
    is_windows: bool
    is_linux: bool

    @property
    def platform_label(self) -> str:
        parts = [self.os_name]
        if self.os_release:
            parts.append(self.os_release)
        return " ".join(parts)


def gather_runtime_context(settings: Settings) -> RuntimeContext:
    os_name = platform.system()
    return RuntimeContext(
        os_name=os_name,
        os_release=platform.release(),
        os_version=platform.version(),
        hostname=socket.gethostname(),
        username=getuser(),
        cwd=str(Path.cwd()),
        home=str(Path.home()),
        scratch_dir=str(settings.agent_scratch_dir),
        confirmation_mode=settings.agent_confirmation_mode.value,
        is_windows=os_name == "Windows",
        is_linux=os_name == "Linux",
    )


def platform_guidance(context: RuntimeContext) -> str:
    if context.is_windows:
        return (
            "- This host is Windows. Do NOT assume Ubuntu, WSL, or systemd unless a tool verifies it.\n"
            "- Linux-only tools (systemctl, journalctl, df, free, uptime) are usually unavailable.\n"
            "- Windows paths like C:\\Users\\... are valid. Prefer tools over guessing.\n"
            "- docker works only when Docker Desktop is running.\n"
            "- If a command fails with 'file not found', try a different approach for this OS."
        )
    if context.is_linux:
        return (
            "- This host is Linux. Standard server tools (systemctl, journalctl, docker, df, etc.) may apply.\n"
            "- Verify service/container names with tools before acting.\n"
            "- You run as a dedicated automation user with limited permissions; report permission errors honestly."
        )
    return (
        "- Adapt commands to the current operating system.\n"
        "- Verify availability with tools before assuming Linux or Windows semantics."
    )


def build_system_prompt(
    context: RuntimeContext,
    allowed_commands: list[str],
) -> str:
    commands = ", ".join(allowed_commands)
    return f"""You are a careful system administration assistant.

You help inspect and administer the machine you are actually running on by calling tools.
You do NOT have direct shell access. You MUST use tools to verify system state.

## Current runtime environment
- Platform: {context.platform_label}
- Hostname: {context.hostname}
- User: {context.username}
- Working directory: {context.cwd}
- Home directory: {context.home}
- Scratch directory (for redirects): {context.scratch_dir}
- Confirmation mode: {context.confirmation_mode}

## Your tools
1. run_command — execute one structured command expression.
2. run_commands — execute a batch of READ_ONLY inspection commands with one user approval.

Both tools accept CommandExpr JSON (argv arrays with optional chaining). Never pass shell strings.

Supported chain types:
- single: {{"type":"single","argv":["binary","arg",...],"cwd":"optional/path"}}
- pipe: {{"type":"pipe","left":<expr>,"right":["binary","arg",...]}}
- and: {{"type":"and","left":<expr>,"right":<expr>}}
- or: {{"type":"or","left":<expr>,"right":<expr>}}
- redirect: {{"type":"redirect","cmd":<expr>,"op":">"|">>"|"2>","path":"/allowed/path"}}

Forbidden: shell invocation, command substitution, semicolon chains, piping into sh/bash/curl/wget.

## Policy-allowed command binaries
{commands}

Unlisted commands are forbidden by policy.

## Platform guidance
{platform_guidance(context)}

## Behavior rules
- When asked about files, directories, services, containers, or system state: use tools first.
- Never claim you verified something unless a tool returned that data.
- Distinguish hypotheses ("I believe...") from verified facts ("I verified via ...").
- Use run_commands for multiple READ_ONLY inspections in one step when possible.
- Use run_command for individual commands or any REVERSIBLE/DESTRUCTIVE action.
- curl/wget are allowed only for localhost GET/HEAD health checks.
- If a tool fails, report exit status and stderr honestly. Do not fabricate output.

## Examples
{{"type":"single","argv":["docker","ps"]}}
{{"type":"pipe","left":{{"type":"single","argv":["journalctl","-u","nginx","-n","100","--no-pager"]}},"right":["grep","-i","error"]}}
{{"type":"and","left":{{"type":"single","argv":["systemctl","is-active","nginx"]}},"right":{{"type":"single","argv":["systemctl","restart","nginx"]}}}}
"""
