import json

COMMAND_EXPR_SCHEMA = {
    "type": "object",
    "description": (
        "Structured command expression using argv arrays. Never use shell strings. "
        "Supported types: single, pipe, and, or, redirect."
    ),
    "properties": {
        "type": {
            "type": "string",
            "enum": ["single", "pipe", "and", "or", "redirect"],
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
                    "execution target. Use argv arrays and supported chain operators "
                    "only. Use this to inspect files, services, docker, logs, or run "
                    "approved actions."
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
                    "Execute a batch of READ_ONLY inspection commands on one "
                    "configured execution target with one user approval."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": target_parameter,
                        "commands": {
                            "type": "array",
                            "items": COMMAND_EXPR_SCHEMA,
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why this batch is needed.",
                        },
                    },
                    "required": ["commands", "reason"],
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
                                "further tools are needed. False if you will continue with "
                                "more run_command or run_commands calls."
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
    "Omitting target runs the command on local (this machine)."
)

COMMAND_DUMP_NUDGE = (
    "The JSON you wrote is assistant text, not a tool call, so nothing ran. "
    "Call run_command (or run_commands) now with target, command, and reason. "
    "Do not print CommandExpr JSON. Redirect paths must be under the scratch directory."
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
    if data.get("type") in {"single", "pipe", "and", "or", "redirect"}:
        return True
    return "command" in data or "commands" in data

CONTINUE_NUDGE = (
    "Your answer was cut off mid-sentence at the end of the assistant message "
    "above. Resume from that exact point so the two parts read as one continuous "
    "answer. Do not add a heading, preamble, apology, or summary of what you "
    "already wrote, and do not start the answer over."
)
