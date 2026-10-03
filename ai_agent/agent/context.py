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
    local_command_user: str
    local_command_home: str

    @property
    def platform_label(self) -> str:
        parts = [self.os_name]
        if self.os_release:
            parts.append(self.os_release)
        return " ".join(parts)


def resolve_local_command_identity(
    *,
    linux_username: str | None = None,
) -> tuple[str, str]:
    """User and home directory for target=local command execution."""
    process_user = getuser()
    process_home = str(Path.home())
    if platform.system() != "Linux" or not linux_username:
        return process_user, process_home
    from ai_agent.commands.run_as import lookup_posix_account

    account = lookup_posix_account(linux_username)
    return account.name, account.home


def gather_runtime_context(
    settings: Settings,
    *,
    linux_username: str | None = None,
) -> RuntimeContext:
    os_name = platform.system()
    local_user, local_home = resolve_local_command_identity(linux_username=linux_username)
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
        local_command_user=local_user,
        local_command_home=local_home,
    )


def platform_guidance(context: RuntimeContext) -> str:
    if context.is_windows:
        return (
            f"- Target `local` is Windows. Local commands run as `{context.local_command_user}` "
            f"(profile `{context.local_command_home}`). File access follows that Windows account.\n"
            "- Do NOT assume Ubuntu, WSL, or systemd on local unless a tool verifies it.\n"
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
            f"- Local commands run as Linux user `{context.local_command_user}` "
            f"(home `{context.local_command_home}`). "
            "File and directory access follows that account's normal permissions.\n"
            "- SSH and Docker targets use each target's configured remote/container user.\n"
            "- Use id, whoami, and pwd when verifying identity; they are READ_ONLY when policy allows.\n"
            "- Report permission errors from tool stderr honestly; do not claim a path is blocked by policy "
            "when the OS denied access."
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
    unlisted_need_approval: bool = False,
) -> str:
    commands = ", ".join(allowed_commands)
    unlisted = (
        "Unlisted commands are not forbidden: they run only after the user explicitly approves them, "
        "every time. Prefer listed commands; use an unlisted one when it is the right tool, and give a clear reason."
        if unlisted_need_approval
        else "Unlisted commands are forbidden by policy."
    )
    target_summaries = targets or [
        TargetSummary(
            name="local",
            kind="local",
            description="This machine (where the agent CLI runs)",
            display="local (this machine)",
        )
    ]
    target_block = format_target_list(target_summaries)
    write_example = str(
        Path(context.local_command_home) / "example.txt",
    )
    return f"""You are a careful system administration assistant.

You help inspect and administer configured machines by calling tools.
You do NOT have direct shell access. You MUST use tools to verify system state.

## Current runtime environment
- Platform: {context.platform_label}
- Hostname: {context.hostname}
- Service process user: {context.username}
- Local target commands run as: {context.local_command_user} (home {context.local_command_home})
- Working directory: {context.cwd}
- Optional scratch directory: {context.scratch_dir}
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
- `local` is the machine running the agent API (`ai-agent serve`), not the user's PC running the chat client.
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
- redirect: {{"type":"redirect","cmd":<expr>,"op":">"|">>"|"2>","path":"/path/in/user/filesystem"}} (small command output only)
- write_file: {{"type":"write_file","path":"/path/to/file","content":"FULL FILE TEXT","append":false}}

Forbidden: shell invocation, command substitution, semicolon chains, piping into sh/bash/curl/wget.

## Saving files (use write_file)
- To create or replace a source/config file, use **write_file** with the full `content` string. Do not use redirect, echo, printf chains, or heredocs.
- The user approves a summary line (path, byte size, short preview) — you still must put the complete content in the tool JSON.
- Example:
  command={{"type":"write_file","path":"{write_example}","content":"# module\\n","append":false}}

## Argv rules (no shell metacharacters)
- Never put `;` in any argv string and never use `;` as its own argv element. Shell chaining is forbidden.
- For multiple inspection steps, use **run_commands** with several separate `single` commands (one approval), or **and** / **or** CommandExpr — not semicolons.
- Searching source trees: prefer **run_commands** with **grep -R** (READ_ONLY), not find -exec.
  Example batch (one tool call):
  commands=[
    {{"type":"single","argv":["grep","-R","-l","PATTERN","--include=*.py","."]}},
    {{"type":"single","argv":["grep","-R","-n","OTHER","--include=*.py","."]}}
  ]
- If you must use find -exec, every piece is its own argv string; end with `"{{}}"` then `"+"` (never `;`):
  {{"type":"single","argv":["find",".","-name","*.py","-exec","grep","-l","PATTERN","{{}}","+"]}}

## Policy-allowed command binaries
{commands}

{unlisted}

## Platform guidance
{platform_guidance(context)}

## Behavior rules
- When asked about files, directories, services, containers, or system state: use tools first.
- Never claim you verified something unless a tool returned that data.
- Distinguish hypotheses ("I believe...") from verified facts ("I verified via ...").
- Use run_commands for multiple READ_ONLY inspections in one step when possible (repo-wide grep, several cats, etc.).
- Use run_command for individual commands or any REVERSIBLE/DESTRUCTIVE action.
- Do not use find for routine repo text search; use grep -R in run_commands instead.
- curl/wget are allowed only for localhost GET/HEAD health checks. Do not use them to create files.
- To write file contents, use **write_file** only. Redirect is for capturing small command stdout, not editing source trees.
- Never put shell operators (`>`, `|`, `&&`) inside an argv string.
- The command field must always be a JSON object with a "type" key, never a shell string.
- If a tool fails, report exit status and stderr honestly. Do not fabricate output.

## Examples (these are run_command arguments — never print them as your reply)
target=home-server command={{"type":"single","argv":["docker","ps"]}}
target=home-server command={{"type":"pipe","left":{{"type":"single","argv":["journalctl","-u","nginx","-n","100","--no-pager"]}},"right":["grep","-i","error"]}}
command={{"type":"and","left":{{"type":"single","argv":["systemctl","is-active","nginx"]}},"right":{{"type":"single","argv":["systemctl","restart","nginx"]}}}}
target=home-server command={{"type":"redirect","cmd":{{"type":"single","argv":["echo","hello from agent"]}},"op":">","path":"{write_example}"}}
"""
