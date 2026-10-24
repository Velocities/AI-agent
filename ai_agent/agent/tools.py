import json

COMMAND_EXPR_SCHEMA = {
    "type": "object",
    "description": (
        "Structured command expression using argv arrays. Never use shell strings. "
        "No semicolons in argv (use run_commands for multiple singles, or and/or). "
        "To create or overwrite a file, use type write_file (not redirect/echo). "
        "Repo search: grep -R in run_commands. find -exec must end with argv "
        "'{}' then '+', never ';'. Types: single, pipe, and, or, redirect, write_file."
    ),
    "properties": {
        "type": {
            "type": "string",
            "enum": ["single", "pipe", "and", "or", "redirect", "write_file"],
        },
        "argv": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Argv array for single commands.",
        },
        "cwd": {"type": "string"},
        "left": {"type": "object", "description": "Left side expression."},
        "right": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Right argv for pipe expressions.",
        },
        "cmd": {"type": "object", "description": "Inner command for redirect."},
        "op": {"type": "string", "enum": [">", ">>", "2>"]},
        "path": {"type": "string"},
        "content": {
            "type": "string",
            "description": "Full UTF-8 file body for write_file only.",
        },
        "append": {
            "type": "boolean",
            "description": "When true with write_file, append instead of truncate.",
        },
    },
    "required": ["type"],
}


def _target_parameter(target_names: list[str]) -> dict:
    return {
        "type": "string",
        "enum": target_names,
        "description": (
            "Configured execution target name. If omitted, the command runs on "
            "'local' (this machine). Never invent hosts, IP addresses, SSH "
            "credentials, or container IDs — pick a name from the enum."
        ),
    }


def build_tool_definitions(target_names: list[str] | None = None) -> list[dict]:
    names = list(target_names) if target_names else ["local"]
    target_parameter = _target_parameter(names)
    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Execute one structured command expression on a configured "
                    "execution target. Use argv arrays only (no shell, no ';' in argv). "
                    "If you already know more than one command, do not call this once "
                    "per command. Call run_commands once with all of them. "
                    "To save source or config files use write_file with path and content "
                    "(not echo/redirect). find -exec requires separate argv elements "
                    "ending with '{}' then '+'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": target_parameter,
                        "command": COMMAND_EXPR_SCHEMA,
                        "reason": {
                            "type": "string",
                            "description": "Why this command is needed.",
                        },
                    },
                    "required": ["command", "reason"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_commands",
                "description": (
                    "Run every command you already intend to run, in one approval. "
                    "Use this whenever the request needs more than one command, "
                    "including commands that are not on the read-only allow-list. "
                    "The user sees the whole batch and can run all of them or only "
                    "some. commands must be a JSON array of objects, never a string. "
                    "Do not put |, &&, or redirects inside argv. "
                    "Default ordering is unordered. Use ordered only when a later "
                    "command is useless unless an earlier one ran; rejecting one "
                    "command then rejects every command after it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": target_parameter,
                        "ordering": {
                            "type": "string",
                            "enum": ["ordered", "unordered"],
                            "description": (
                                "unordered: each command stands alone. This is the "
                                "right choice for independent checks such as uptime, "
                                "df, free, and last. The user may run any subset. "
                                "ordered: a later command is useless unless an earlier "
                                "one ran. Rejecting one then rejects every command "
                                "after it. Do not use ordered just because you listed "
                                "the commands in a sensible order."
                            ),
                        },
                        "commands": {
                            "type": "array",
                            "description": (
                                "JSON array of command objects, one per command. "
                                "Never wrap the array in a string."
                            ),
                            "items": COMMAND_EXPR_SCHEMA,
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why this batch is needed.",
                        },
                    },
                    "required": ["commands", "reason", "ordering"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "respond",
                "description": (
                    "Optional. Send a short progress note while you are still working, using "
                    "finished=false. Do not use this for your final answer: write the final "
                    "answer as ordinary assistant text so it streams to the user as you type it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "finished": {
                            "type": "boolean",
                            "description": (
                                "True only when the user's request is fully complete and no "
                                "further tools are needed. False only when output you "
                                "have not seen yet will decide the next command. If you "
                                "already know the commands, use one run_commands call "
                                "instead of continuing one command at a time."
                            ),
                        },
                        "message": {
                            "type": "string",
                            "description": (
                                "Brief status note describing what you are doing next."
                            ),
                        },
                    },
                    "required": ["finished", "message"],
                },
            },
        },
    ]


TOOL_DEFINITIONS = build_tool_definitions()

SCHEMA_NUDGE = (
    "Answer the user now as ordinary assistant text, or call run_command / "
    "run_commands if you still need to inspect a configured execution target. "
    "Omitting target runs the command on local (this machine). "
    "run_commands must set ordering to ordered or unordered."
)

COMMAND_DUMP_NUDGE = (
    "The JSON you wrote is assistant text, not a tool call, so nothing ran. "
    "Call run_command (or run_commands) now with target, command, and reason. "
    "Do not print CommandExpr JSON. No semicolons in argv — use run_commands for "
    "multiple grep -R steps, and set ordering to ordered or unordered. "
    "find -exec needs argv ending with '{}' then '+'."
)


def looks_like_command_dump(text: str) -> bool:
    """True when the model printed a CommandExpr instead of calling a tool."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            stripped = "\n".join(lines[1:-1]).strip()
    if not stripped.startswith("{"):
        return False
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("type") in {"single", "pipe", "and", "or", "redirect", "write_file"}:
        return True
    return "command" in data or "commands" in data

CONTINUE_NUDGE = (
    "Your answer was cut off mid-sentence at the end of the assistant message "
    "above. Resume from that exact point so the two parts read as one continuous "
    "answer. Do not add a heading, preamble, apology, or summary of what you "
    "already wrote, and do not start the answer over."
)
