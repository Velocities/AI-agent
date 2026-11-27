"""JSON the model reads after a command, and the audit row for that outcome."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.ast import CommandExpr
from ai_agent.commands.render import render_command
from ai_agent.execution_targets.base import ExecutionTarget
from ai_agent.llm.base import LLMMessage, ToolCall
from ai_agent.policy.engine import PolicyDecision
from ai_agent.workflows.manifests import WorkflowError, WorkflowTool, parse_tool_output

logger = logging.getLogger(__name__)


def tool_message(call: ToolCall, payload: dict | list) -> LLMMessage:
    return LLMMessage(
        role="tool",
        name=call.name,
        content=json.dumps(payload, ensure_ascii=True),
        tool_call_id=call.id,
    )


def failure_message(call: ToolCall, error: str) -> LLMMessage:
    return tool_message(call, {"success": False, "error": error})


def respond_result(call: ToolCall) -> tuple[LLMMessage, str | None]:
    """The tool message, and the user-visible answer when the model is done"""
    finished = call.arguments.get("finished")
    message = call.arguments.get("message", "")
    if not isinstance(finished, bool):
        return failure_message(call, "respond requires finished to be a boolean"), None
    if finished:
        return tool_message(call, {"success": True, "finished": True}), message
    return (
        tool_message(
            call,
            {
                "success": True,
                "finished": False,
                "note": "Continue with command tools, then call respond when done.",
            },
        ),
        None,
    )


def policy_rejection(decision: PolicyDecision) -> dict:
    return {
        "success": False,
        "error": decision.reason,
        "policy_denied": True,
    }


def user_rejection() -> dict:
    return {
        "success": False,
        "error": "User denied command execution",
        "user_denied": True,
    }


def run_command(
    target: ExecutionTarget | None,
    expr: CommandExpr,
    target_name: str,
    runner: Callable[[], object] | None = None,
) -> dict:
    """Start the process and return its output. Does not ask for permission."""
    if target is None:
        return {
            "success": False,
            "error": f"Unknown execution target {target_name!r}",
        }
    logger.info("Running on %s: %s", target_name, render_command(expr))
    result = runner() if runner is not None else target.run(expr)
    payload = result.as_tool_payload()
    if result.truncated:
        payload["note"] = "Output was truncated before being returned to the model."
    payload.setdefault("rendered_command", render_command(expr))
    payload["execution_target"] = {
        "name": target_name,
        "kind": target.kind,
    }
    logger.info("Finished on %s success=%s", target_name, payload.get("success"))
    return payload


def workflow_tool_result(payload: dict, tool: WorkflowTool) -> dict:
    """Return parsed tool JSON only. Do not echo raw stdout to the model."""
    slim: dict = {
        "success": payload.get("success", False),
        "exit_status": payload.get("exit_status"),
        "execution_target": payload.get("execution_target"),
    }
    stdout = payload.get("stdout")
    if payload.get("success") and isinstance(stdout, str):
        try:
            slim["output"] = parse_tool_output(tool, stdout)
        except WorkflowError as exc:
            slim["success"] = False
            slim["error"] = str(exc)
        return slim
    if payload.get("error"):
        slim["error"] = payload["error"]
    if payload.get("stderr"):
        slim["stderr"] = payload["stderr"]
    if payload.get("user_denied"):
        slim["user_denied"] = True
    if payload.get("policy_denied"):
        slim["policy_denied"] = True
    return slim


def record_command_audit(
    audit: AuditLogger,
    *,
    session_id: str,
    tool_name: str,
    arguments: dict,
    decision: PolicyDecision,
    confirmation_required: bool,
    confirmation_granted: bool,
    result: dict,
    error: str | None,
    execution_target: str,
) -> None:
    audit.log_event(
        session_id=session_id,
        tool_name=tool_name,
        arguments=arguments,
        decision=decision,
        confirmation_required=confirmation_required,
        confirmation_granted=confirmation_granted,
        result=result,
        error=error,
        execution_target=execution_target,
    )


def latest_tool_error(messages: list[LLMMessage]) -> str | None:
    """Return a stable error string from the newest tool result, if it failed."""
    for message in reversed(messages):
        if message.role != "tool":
            if message.role == "assistant":
                continue
            return None
        raw = message.content or ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip() or None
        if isinstance(payload, list):
            errors = [
                item.get("error")
                for item in payload
                if isinstance(item, dict) and item.get("success") is False
            ]
            if not errors or any(not isinstance(err, str) or not err for err in errors):
                return None
            return " | ".join(errors)
        if isinstance(payload, dict) and payload.get("success") is False:
            error = payload.get("error")
            return error if isinstance(error, str) and error else None
        return None
    return None
