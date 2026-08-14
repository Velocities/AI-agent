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

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute one structured Linux command expression. "
                "Use argv arrays and supported chain operators only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
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
                "Execute a batch of READ_ONLY inspection commands with one user approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
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
]

SYSTEM_PROMPT = """You are a careful Linux server administrator assistant.

Rules:
- You operate on an Ubuntu server through structured command tools only.
- Never claim you verified server state unless a tool actually returned that data.
- Distinguish clearly between hypotheses ("I believe...") and verified facts ("I verified...").
- Use run_commands for multi-step READ_ONLY inspection batches when possible.
- Use run_command for individual commands or any REVERSIBLE/DESTRUCTIVE action.
- Commands must use argv arrays, not shell strings.
- Supported chaining types: pipe (|), and (&&), or (||), and limited redirect (> >> 2>).
- Forbidden: shell invocation, command substitution, semicolon chains, piping into sh/bash/curl.
- curl/wget are allowed only for localhost GET/HEAD health checks.
- If a tool fails or permission is denied, report the failure honestly.
- Prefer docker, journalctl, systemctl, and other reliable diagnostics for debugging.

Command expression examples:
{"type":"single","argv":["df","-h"]}
{"type":"pipe","left":{"type":"single","argv":["journalctl","-u","nginx","-n","100","--no-pager"]},"right":["grep","-i","error"]}
{"type":"and","left":{"type":"single","argv":["systemctl","is-active","nginx"]},"right":{"type":"single","argv":["systemctl","restart","nginx"]}}
"""
