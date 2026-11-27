"""Turn tool-call JSON into command expressions. This module does not run them."""

from __future__ import annotations

import json
import logging
import re

from ai_agent.commands.ast import CommandExpr, parse_command_expr
from ai_agent.commands.validate import command_expression_issue
from ai_agent.execution_targets.base import ExecutionTarget, UnknownExecutionTarget
from ai_agent.execution_targets.router import ExecutionTargetRouter
from ai_agent.policy.engine import PolicyDecision, PolicyEngine
from ai_agent.policy.risk import RiskLevel

logger = logging.getLogger(__name__)

STRING_COMMANDS_ERROR = (
    "commands must be a JSON array of command objects, not a string. "
    "Call run_commands again with commands as an array. "
    "Do not split the batch into separate run_command calls."
)

WORKFLOW_POLICY_REASON = (
    "Workflow target: commands run in an isolated container; host policy does not apply."
)

JSON_ESCAPE_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)")
PATH_FLAGS = frozenset({"-LiteralPath", "-Path", "-Destination", "-FilePath"})


def repair_json_escapes(text: str) -> str:
    """Turn invalid JSON backslash escapes into literal backslashes."""

    def replace(match: re.Match[str]) -> str:
        body = match.group(1)
        if body.startswith("u") and len(body) == 5:
            return match.group(0)
        if body in '"\\/bfnrt':
            return match.group(0)
        if body == "'":
            return "'"
        return "\\\\" + body

    return JSON_ESCAPE_RE.sub(replace, text)


def loads_commands_json(value: str) -> list | None:
    for candidate in (value, repair_json_escapes(value)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
    return None


def normalize_path_arg(value: str) -> str:
    """Strip wrapping quotes and collapse over-escaped Windows backslashes."""
    path = value.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in {"'", '"'}:
        path = path[1:-1]
    while "\\\\" in path:
        collapsed = path.replace("\\\\", "\\")
        if collapsed == path:
            break
        path = collapsed
    return path


def normalize_command_paths(commands: list) -> list:
    """Fix common llama path mangling on PowerShell -LiteralPath values."""
    for item in commands:
        if not isinstance(item, dict):
            continue
        argv = item.get("argv")
        if not isinstance(argv, list):
            continue
        fixed: list[object] = []
        index = 0
        changed = False
        while index < len(argv):
            arg = argv[index]
            fixed.append(arg)
            if (
                isinstance(arg, str)
                and arg in PATH_FLAGS
                and index + 1 < len(argv)
                and isinstance(argv[index + 1], str)
            ):
                original = argv[index + 1]
                normalized = normalize_path_arg(original)
                if normalized != original:
                    changed = True
                    logger.info(
                        "Normalized path arg %s: %r -> %r",
                        arg,
                        original,
                        normalized,
                    )
                fixed.append(normalized)
                index += 2
                continue
            index += 1
        if changed:
            item["argv"] = fixed
    return commands


def coerce_command_list(value: object) -> tuple[list | None, str | None]:
    """Accept the array models send, and the same array wrapped in a string."""
    if isinstance(value, list):
        return normalize_command_paths(value), None
    if isinstance(value, str):
        parsed = loads_commands_json(value)
        if parsed is not None:
            logger.info(
                "Coerced stringified commands JSON into array (%s commands)",
                len(parsed),
            )
            return normalize_command_paths(parsed), None
        logger.warning(
            "Failed to coerce commands string (%s chars): %s",
            len(value),
            value[:180],
        )
        return None, STRING_COMMANDS_ERROR
    return None, "commands must be an array of command expressions"


def parse_command_structure(command_data: object) -> tuple[CommandExpr | None, str | None]:
    """Return a command expression, or the reason the JSON is not one."""
    if not isinstance(command_data, dict):
        return None, "command must be a JSON object with a type field"
    try:
        expr = parse_command_expr(command_data)
    except Exception as exc:
        return None, f"Invalid command expression: {exc}"
    issue = command_expression_issue(expr)
    if issue:
        return None, issue
    return expr, None


def workflow_policy_decision(expr: CommandExpr) -> PolicyDecision:
    return PolicyDecision(
        expr=expr,
        effective_risk=RiskLevel.READ_ONLY,
        segments=[],
        allowed=True,
        reason=WORKFLOW_POLICY_REASON,
    )


def policy_decision(
    policy: PolicyEngine,
    expr: CommandExpr,
    target: ExecutionTarget | None,
) -> PolicyDecision:
    if target is not None and not target.uses_host_policy:
        return workflow_policy_decision(expr)
    return policy.verify(expr)


def resolve_target(
    router: ExecutionTargetRouter,
    arguments: dict,
) -> tuple[str, ExecutionTarget | None, str | None]:
    raw = arguments.get("target")
    if raw is None or raw == "":
        name = router.default_name
    elif not isinstance(raw, str):
        return "", None, "target must be a configured name (string)"
    else:
        name = raw
    try:
        return name, router.resolve(name), None
    except UnknownExecutionTarget as exc:
        return name, None, str(exc)
