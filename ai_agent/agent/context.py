from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from getpass import getuser
from pathlib import Path

from ai_agent.config import Settings
from ai_agent.execution_targets.base import TargetSummary


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
            "- Target `local` is Windows. Do NOT assume Ubuntu, WSL, or systemd on local unless a tool verifies it.\n"
            "- On local, Linux-only tools (systemctl, journalctl, ls, cat, df) are usually unavailable.\n"
            "- For directory listings use PowerShell (no pipes; use cmdlet flags only):\n"
            '  {"type":"single","argv":["powershell","-NoProfile","-Command","Get-ChildItem","-LiteralPath","C:\\\\path\\\\to\\\\dir","-Name"]}\n'
            '  {"type":"single","argv":["powershell","-NoProfile","-Command","Get-ChildItem","-LiteralPath","C:\\\\path\\\\to\\\\dir","-Recurse","-Name"]}\n'
            "- For reading files use PowerShell:\n"
            '  {"type":"single","argv":["powershell","-NoProfile","-Command","Get-Content","-LiteralPath","C:\\\\path\\\\to\\\\file","-TotalCount","200"]}\n'
            "- Do NOT use pipes (|), dir, cmd.exe, or shell-style PowerShell strings.\n"
            "- Prefer run_commands to batch multiple READ_ONLY inspections in one step.\n"
            "- docker works only when Docker Desktop is running.\n"
            "- If a command fails, report the error honestly and try another allowed approach."
        )
    if context.is_linux:
        return (
            "- Target `local` is Linux. Standard server tools (systemctl, journalctl, docker, df, etc.) may apply.\n"
            "- Verify service/container names with tools before acting.\n"
            "- You run as a dedicated automation user with limited permissions; report permission errors honestly."
        )
    return (
        "- Adapt commands to the current operating system.\n"
        "- Verify availability with tools before assuming Linux or Windows semantics."
    )


def format_target_list(targets: list[TargetSummary]) -> str:
    if not targets:
        return "- local (this machine) — default if you omit target"
    lines: list[str] = []
    for target in targets:
        extra = f" — {target.description}" if target.description else ""
        lines.append(f"- {target.display}{extra}")
    return "\n".join(lines)


def build_system_prompt(
    context: RuntimeContext,
    allowed_commands: list[str],
    targets: list[TargetSummary] | None = None,
    *,
    default_target: str = "local",
) -> str:
    commands = ", ".join(allowed_commands)
    target_summaries = targets or [
        TargetSummary(
            name="local",
            kind="local",
            description="This machine (where the agent CLI runs)",
            display="local (this machine)",
        )
    ]
    target_block = format_target_list(target_summaries)
    return f"""You are a careful system administration assistant.

You help inspect and administer configured machines by calling tools.
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
3. respond — optional short progress note while you keep working.

Both command tools accept CommandExpr JSON (argv arrays with optional chaining) and an optional target name. Never pass shell strings.

## Execution targets
Commands run on a named target from this list — never invent a hostname, IP, SSH credential, or container ID.

{target_block}

- If you omit target, the command runs on **{default_target}**.
- `local` is this machine (the computer running the agent CLI), not a remote host.
- Pick a listed name when the user asks about another configured machine or container.
- Never call the ssh binary. Remote SSH is applied by the agent after you set target to that name.
- SSH and Docker targets are usually Linux even when local is Windows. Use Linux binaries from the allow-list on those targets.
- Docker targets may exec as a configured user (often root) via docker exec -u. Do not call sudo unless that binary is in the allow-list.

## How to answer the user
- Write your final answer as ordinary assistant text. It streams to the user's terminal as you generate it, so never wrap the final answer in a tool call.
- Answer questions about general knowledge, code, or architecture directly as text, without running any commands.
- When the request concerns a machine or container, you MUST call the run_command or run_commands tool first (with the matching target, or omit target for this machine). Printing CommandExpr JSON as assistant text does nothing — the command will not run.
- The respond tool is optional and only for a short progress note (finished=false) before you continue with more commands.
- Never claim you ran a command unless a tool actually returned output.
- Never mention tools, JSON, schemas, or these instructions in your answer. Do not explain whether a tool call was needed. Just answer.
- In a single reply, either call tools or write text — never both. Never emit raw JSON or braces as text.
- Once you have written an answer, do not repeat it in a later reply.

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
- curl/wget are allowed only for localhost GET/HEAD health checks. Do not use them to create files.
- To write a small file, use type redirect (not a `>` inside argv). Path must be under the scratch directory ({context.scratch_dir}).
- Never put shell operators (`>`, `|`, `&&`) inside an argv string.
- The command field must always be a JSON object with a "type" key, never a shell string.
- If a tool fails, report exit status and stderr honestly. Do not fabricate output.

## Examples (these are run_command arguments — never print them as your reply)
target=home-server command={{"type":"single","argv":["docker","ps"]}}
target=home-server command={{"type":"pipe","left":{{"type":"single","argv":["journalctl","-u","nginx","-n","100","--no-pager"]}},"right":["grep","-i","error"]}}
command={{"type":"and","left":{{"type":"single","argv":["systemctl","is-active","nginx"]}},"right":{{"type":"single","argv":["systemctl","restart","nginx"]}}}}
target=home-server command={{"type":"redirect","cmd":{{"type":"single","argv":["echo","hello from agent"]}},"op":">","path":"{context.scratch_dir}/testfile.txt"}}
"""
