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
                "Execute one structured command expression on the current host. "
                "Use argv arrays and supported chain operators only. "
                "Use this to inspect files, services, docker, logs, or run approved actions."
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
    {
        "type": "function",
        "function": {
            "name": "respond",
            "description": (
                "Send a message to the user and explicitly declare whether work on the "
                "current request is finished. You must call this tool to communicate with "
                "the user—plain assistant text is not shown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            "User-facing message. When finished=true, provide the complete "
                            "answer. When finished=false, optional brief internal status."
                        ),
                    },
                    "finished": {
                        "type": "boolean",
                        "description": (
                            "True only when the user's request is fully complete and no "
                            "further tools are needed. False if you will continue with "
                            "more run_command or run_commands calls."
                        ),
                    },
                },
                "required": ["message", "finished"],
            },
        },
    },
]

SCHEMA_NUDGE = (
    "Use the respond tool to communicate with the user. "
    "Set finished=true only when the request is fully complete."
)
