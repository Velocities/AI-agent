from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from ai_agent.approval.prompt import ApprovalPrompter, ApprovalResult, PendingCommand
from ai_agent.approval.selection import (
    apply_batch_approval,
    approval_flags,
    batch_ordering,
    order_groups_for,
)
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.ast import CommandExpr, SingleCommand, parse_command_expr
from ai_agent.commands.render import render_command
from ai_agent.commands.validate import command_expression_issue
from ai_agent.execution_targets.base import ExecutionTarget, UnknownExecutionTarget
from ai_agent.execution_targets.router import ExecutionTargetRouter
from ai_agent.execution_targets.sandbox import SANDBOX_TARGET_NAME, SandboxExecutionTarget
from ai_agent.llm.base import LLMMessage, ToolCall
from ai_agent.policy.engine import PolicyDecision, PolicyEngine
from ai_agent.policy.risk import RiskLevel
from ai_agent.workflows.manifests import (
    WorkflowError,
    WorkflowManifest,
    parse_tool_output,
    validate_tool_input,
)

_STRING_COMMANDS_ERROR = (
    "commands must be a JSON array of command objects, not a string. "
    "Call run_commands again with commands as an array. "
    "Do not split the batch into separate run_command calls."
)

_SANDBOX_POLICY_REASON = (
    "Workflow target: commands run in an isolated container; host policy does not apply."
)


def coerce_command_list(value: object) -> tuple[list | None, str | None]:
    """Accept the array models send, and the same array wrapped in a string.

    Smaller models often encode ``commands`` as a string of JSON. That used
    to fail the batch, after which the model retried each command alone.
    """
    if isinstance(value, list):
        return value, None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return parsed, None
        return None, _STRING_COMMANDS_ERROR
    return None, "commands must be an array of command expressions"


@dataclass(frozen=True)
class PreparedCommand:
    """One command from a run_commands list, or the reason it did not parse."""

    expr: CommandExpr | None
    pending: PendingCommand | None
    error: str | None


class ToolHandler:
    """Turn tool calls into tool messages: commands, respond, and unknown tools."""

    def __init__(
        self,
        policy: PolicyEngine,
        prompter: ApprovalPrompter,
        router: ExecutionTargetRouter,
        audit: AuditLogger,
        session: ApprovalSession,
        workflow: WorkflowManifest | None = None,
    ) -> None:
        self.policy = policy
        self.prompter = prompter
        self.router = router
        self.audit = audit
        self.session = session
        self.workflow = workflow

    @staticmethod
    def _sandbox_policy_decision(expr: CommandExpr) -> PolicyDecision:
        return PolicyDecision(
            expr=expr,
            effective_risk=RiskLevel.READ_ONLY,
            segments=[],
            allowed=True,
            reason=_SANDBOX_POLICY_REASON,
        )

    def _policy_decision(
        self, expr: CommandExpr, target: ExecutionTarget | None
    ) -> PolicyDecision:
        if target is not None and not target.uses_host_policy:
            return self._sandbox_policy_decision(expr)
        return self.policy.evaluate(expr)

    def _process_tool_calls(
        self,
        tool_calls: list[ToolCall],
        append: Callable[[LLMMessage], None],
    ) -> str | None:
        final_message: str | None = None
        command_calls = [
            call for call in tool_calls if call.name in {"run_command", "run_commands"}
        ]
        other_calls = [
            call for call in tool_calls if call.name not in {"run_command", "run_commands"}
        ]

        if len(command_calls) > 1 and len(other_calls) == 0:
            tool_messages = self._handle_batch_tool_calls(command_calls)
        else:
            tool_messages = []
            for call in tool_calls:
                if call.name == "respond":
                    tool_message, finished_message = self._handle_respond(call)
                    tool_messages.append(tool_message)
                    if finished_message is not None:
                        final_message = finished_message
                else:
                    tool_messages.append(self._handle_tool_call(call))

        for tool_message in tool_messages:
            append(tool_message)
        return final_message

    def _handle_respond(self, call: ToolCall) -> tuple[LLMMessage, str | None]:
        finished = call.arguments.get("finished")
        message = call.arguments.get("message", "")

        if not isinstance(finished, bool):
            payload = {
                "success": False,
                "error": "respond requires finished to be a boolean",
            }
            return (
                LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                ),
                None,
            )

        if finished:
            payload = {"success": True, "finished": True}
            return (
                LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                ),
                message,
            )

        payload = {
            "success": True,
            "finished": False,
            "note": "Continue with command tools, then call respond when done.",
        }
        return (
            LLMMessage(
                role="tool",
                name=call.name,
                content=json.dumps(payload, ensure_ascii=True),
                tool_call_id=call.id,
            ),
            None,
        )

    def _handle_batch_tool_calls(self, tool_calls: list[ToolCall]) -> list[LLMMessage]:
        def abandon_batch() -> list[LLMMessage]:
            # The combined approval is over. Each call is handled by itself,
            # which is why this returns one tool message per call.
            return [self._handle_tool_call(item) for item in tool_calls]

        pending: list[PendingCommand] = []
        call_map: list[tuple[ToolCall, object, str, ExecutionTarget | None]] = []
        groups: list[int | None] = []
        next_group = 0

        for call in tool_calls:
            if call.name == "run_commands":
                commands, commands_error = coerce_command_list(
                    call.arguments.get("commands", [])
                )
                if commands_error or commands is None:
                    return abandon_batch()
                call.arguments["commands"] = commands
                ordering, ordering_error = batch_ordering(call.arguments)
                if ordering_error:
                    return abandon_batch()
                group: int | None = None
                if ordering == "ordered":
                    group = next_group
                    next_group += 1
                # An empty list never looks up a target. A bad target, or any
                # command that does not parse, drops the whole combined batch.
                target_name = ""
                target: ExecutionTarget | None = None
                if commands:
                    target_name, target, target_error = self._resolve_target(
                        call.arguments
                    )
                    if target_error:
                        return abandon_batch()
                prepared = self._prepare_commands(commands, call.arguments, target)
                if any(item.error for item in prepared):
                    return abandon_batch()
                for item in prepared:
                    assert item.expr is not None and item.pending is not None
                    pending.append(item.pending)
                    call_map.append((call, item.expr, target_name, target))
                    groups.append(group)
            elif call.name == "run_command":
                expr, parse_error = self._parse_command_for_tool(
                    call.arguments.get("command", {})
                )
                if parse_error:
                    return abandon_batch()
                assert expr is not None
                target_name, target, target_error = self._resolve_target(
                    call.arguments
                )
                if target_error:
                    return abandon_batch()
                decision = self._policy_decision(expr, target)
                pending.append(
                    PendingCommand(
                        expr=expr,
                        decision=decision,
                        reason=call.arguments.get("reason"),
                        target_display=target.display() if target else None,
                        target_name=target.name if target else None,
                        target_kind=target.kind if target else None,
                    )
                )
                call_map.append((call, expr, target_name, target))
                groups.append(None)

        sandbox_batch = all(
            target is not None and not target.uses_host_policy
            for _call, _expr, _target_name, target in call_map
        )
        if sandbox_batch:
            flags = [True] * len(pending)
            approval = None
        else:
            approval = self.prompter.prompt_batch(pending, order_groups=groups)
            flags = approval_flags(approval.approved, approval.accepted, len(pending))
        payloads: list[dict] = []
        for index, ((call, expr, target_name, target), item) in enumerate(
            zip(call_map, pending, strict=True)
        ):
            payloads.append(
                self._execute_with_audit(
                    tool_name=call.name,
                    arguments=call.arguments,
                    expr=expr,
                    decision=item.decision,
                    approved=flags[index],
                    target_name=target_name,
                    target=target,
                )
            )
        self._annotate_partial_batch(payloads, approval)
        return [
            LLMMessage(
                role="tool",
                name=call.name,
                content=json.dumps(payload, ensure_ascii=True),
                tool_call_id=call.id,
            )
            for payload, (call, _expr, _target_name, _target) in zip(
                payloads, call_map, strict=True
            )
        ]

    def _handle_tool_call(self, call: ToolCall) -> LLMMessage:
        if call.name == "run_tool":
            return self._handle_run_tool(call)

        if call.name == "run_commands":
            commands, commands_error = coerce_command_list(call.arguments.get("commands", []))
            if commands_error or commands is None:
                payload = {"success": False, "error": commands_error}
                return LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                )
            call.arguments["commands"] = commands

            ordering, ordering_error = batch_ordering(call.arguments)
            if ordering_error:
                payload = {"success": False, "error": ordering_error}
                return LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                )
            target_name, target, target_error = self._resolve_target(call.arguments)
            if target_error:
                payload = {"success": False, "error": target_error}
                return LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                )
            # A command that does not parse is one failed entry. The others still run.
            prepared = self._prepare_commands(commands, call.arguments, target)
            pending = [item.pending for item in prepared if item.pending is not None]

            if target is not None and not target.uses_host_policy:
                approval = None
                flags = [True] * len(pending)
            else:
                approval = (
                    self.prompter.prompt_batch(
                        pending,
                        order_groups=order_groups_for(ordering, len(pending)),
                    )
                    if pending
                    else None
                )
                flags = (
                    approval_flags(approval.approved, approval.accepted, len(pending))
                    if approval is not None
                    else []
                )
            flag_iter = iter(flags)
            payloads = []
            decided: list[dict] = []
            for item in prepared:
                if item.error is not None:
                    payloads.append({"success": False, "error": item.error})
                    continue
                assert item.expr is not None and item.pending is not None
                payload = self._execute_with_audit(
                    tool_name=call.name,
                    arguments=call.arguments,
                    expr=item.expr,
                    decision=item.pending.decision,
                    approved=next(flag_iter),
                    target_name=target_name,
                    target=target,
                )
                payloads.append(payload)
                decided.append(payload)
            if approval is not None:
                self._annotate_partial_batch(decided, approval)
            return LLMMessage(
                role="tool",
                name=call.name,
                content=json.dumps(payloads, ensure_ascii=True),
                tool_call_id=call.id,
            )

        if call.name == "run_command":
            expr, parse_error = self._parse_command_for_tool(
                call.arguments.get("command", {})
            )
            if parse_error:
                payload = {"success": False, "error": parse_error}
                return LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                )
            assert expr is not None

            target_name, target, target_error = self._resolve_target(call.arguments)
            if target_error:
                payload = {"success": False, "error": target_error}
                return LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                )

            decision = self._policy_decision(expr, target)
            if target is not None and not target.uses_host_policy:
                approval_granted = True
            elif self.prompter.should_auto_run(decision):
                approval_granted = True
            else:
                approval = self.prompter.prompt_single(
                    decision,
                    reason=call.arguments.get("reason"),
                    target_display=target.display() if target else None,
                    target_name=target.name if target else None,
                    target_kind=target.kind if target else None,
                )
                approval_granted = approval.approved

            payload = self._execute_with_audit(
                tool_name=call.name,
                arguments=call.arguments,
                expr=expr,
                decision=decision,
                approved=approval_granted,
                target_name=target_name,
                target=target,
            )
            return LLMMessage(
                role="tool",
                name=call.name,
                content=json.dumps(payload, ensure_ascii=True),
                tool_call_id=call.id,
            )

        payload = {"success": False, "error": f"Unknown tool: {call.name}"}
        return LLMMessage(
            role="tool",
            name=call.name,
            content=json.dumps(payload, ensure_ascii=True),
            tool_call_id=call.id,
        )

    def _handle_run_tool(self, call: ToolCall) -> LLMMessage:
        """Run a manifest tool inside the sandbox. The entrypoint comes from the manifest."""
        if self.workflow is None:
            return self._tool_error(call, "run_tool is only available inside a workflow session")
        name = call.arguments.get("tool")
        raw_input = call.arguments.get("input")
        if not isinstance(name, str):
            return self._tool_error(call, "tool must be a workflow tool name")
        try:
            tool = self.workflow.tool(name)
            validate_tool_input(tool, raw_input)
        except WorkflowError as exc:
            return self._tool_error(call, str(exc))
        try:
            target = self.router.resolve(SANDBOX_TARGET_NAME)
        except UnknownExecutionTarget as exc:
            return self._tool_error(call, str(exc))
        if not isinstance(target, SandboxExecutionTarget):
            return self._tool_error(call, "run_tool requires the sandbox execution target")
        expr = SingleCommand(argv=[tool.entrypoint])
        decision = self._sandbox_policy_decision(expr)
        approved = True
        stdin_text = json.dumps(raw_input)
        payload = self._execute_with_audit(
            tool_name=call.name,
            arguments=call.arguments,
            expr=expr,
            decision=decision,
            approved=approved,
            target_name=target.name,
            target=target,
            runner=lambda: target.run_tool(tool.entrypoint, stdin_text),
        )
        payload = self._run_tool_payload(payload, tool)
        return LLMMessage(
            role="tool",
            name=call.name,
            content=json.dumps(payload, ensure_ascii=True),
            tool_call_id=call.id,
        )

    @staticmethod
    def _run_tool_payload(payload: dict, tool: WorkflowTool) -> dict:
        """Return parsed tool JSON only — do not echo raw stdout to the model."""
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

    def _tool_error(self, call: ToolCall, message: str) -> LLMMessage:
        payload = {"success": False, "error": message}
        return LLMMessage(
            role="tool",
            name=call.name,
            content=json.dumps(payload, ensure_ascii=True),
            tool_call_id=call.id,
        )

    def _prepare_commands(
        self,
        commands: list,
        arguments: dict,
        target: ExecutionTarget | None,
    ) -> list[PreparedCommand]:
        """Parse every command and build a pending approval for each one that parses.

        The returned list has one entry per command, in order. An entry with
        ``error`` set did not parse. Callers choose what that means.
        """
        prepared: list[PreparedCommand] = []
        for command_data in commands:
            expr, parse_error = self._parse_command_for_tool(command_data)
            if parse_error:
                prepared.append(
                    PreparedCommand(expr=None, pending=None, error=parse_error)
                )
                continue
            assert expr is not None
            prepared.append(
                PreparedCommand(
                    expr=expr,
                    pending=PendingCommand(
                        expr=expr,
                        decision=self._policy_decision(expr, target),
                        reason=arguments.get("reason"),
                        target_display=target.display() if target else None,
                        target_name=target.name if target else None,
                        target_kind=target.kind if target else None,
                    ),
                    error=None,
                )
            )
        return prepared

    @staticmethod
    def _parse_command_for_tool(
        command_data: object,
    ) -> tuple[CommandExpr | None, str | None]:
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

    def _resolve_target(
        self, arguments: dict
    ) -> tuple[str, ExecutionTarget | None, str | None]:
        raw = arguments.get("target")
        if raw is None or raw == "":
            name = self.router.default_name
        elif not isinstance(raw, str):
            return "", None, "target must be a configured name (string)"
        else:
            name = raw
        try:
            return name, self.router.resolve(name), None
        except UnknownExecutionTarget as exc:
            return name, None, str(exc)

    def _execute_with_audit(
        self,
        *,
        tool_name: str,
        arguments: dict,
        expr,
        decision,
        approved: bool,
        target_name: str,
        target: ExecutionTarget | None,
        runner: Callable[[], object] | None = None,
    ) -> dict:
        payload = self._run_audited(
            tool_name=tool_name,
            arguments=arguments,
            expr=expr,
            decision=decision,
            approved=approved,
            target_name=target_name,
            target=target,
            runner=runner,
        )
        payload.setdefault("rendered_command", render_command(expr))
        payload["execution_target"] = {
            "name": target_name,
            "kind": target.kind if target else None,
        }
        return payload

    @staticmethod
    def _annotate_partial_batch(payloads: list[dict], approval: ApprovalResult) -> None:
        apply_batch_approval(
            payloads,
            accepted=approval.accepted,
            cascade_rejected=approval.cascade_rejected,
        )

    def _run_audited(
        self,
        *,
        tool_name: str,
        arguments: dict,
        expr,
        decision,
        approved: bool,
        target_name: str,
        target: ExecutionTarget | None,
        runner: Callable[[], object] | None = None,
    ) -> dict:
        skip_host_approval = target is not None and not target.uses_host_policy
        confirmation_required = (
            not skip_host_approval and not self.prompter.should_auto_run(decision)
        )
        if not decision.allowed:
            payload = {
                "success": False,
                "error": decision.reason,
                "policy_denied": True,
            }
            self.audit.log_event(
                session_id=self.session.session_id,
                tool_name=tool_name,
                arguments=arguments,
                decision=decision,
                confirmation_required=confirmation_required,
                confirmation_granted=False,
                result=payload,
                error=decision.reason,
                execution_target=target_name,
            )
            return payload

        if not approved:
            payload = {
                "success": False,
                "error": "User denied command execution",
                "user_denied": True,
            }
            self.audit.log_event(
                session_id=self.session.session_id,
                tool_name=tool_name,
                arguments=arguments,
                decision=decision,
                confirmation_required=confirmation_required,
                confirmation_granted=False,
                result=payload,
                error="user_denied",
                execution_target=target_name,
            )
            return payload

        if target is None:
            payload = {
                "success": False,
                "error": f"Unknown execution target {target_name!r}",
            }
            return payload

        result = runner() if runner is not None else target.run(expr)
        payload = result.as_tool_payload()
        if result.truncated:
            payload["note"] = "Output was truncated before being returned to the model."
        self.audit.log_event(
            session_id=self.session.session_id,
            tool_name=tool_name,
            arguments=arguments,
            decision=decision,
            confirmation_required=confirmation_required,
            confirmation_granted=True,
            result=payload,
            execution_target=target_name,
        )
        return payload

