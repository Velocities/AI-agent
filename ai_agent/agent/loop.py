from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ai_agent.agent.context import build_system_prompt, gather_runtime_context
from ai_agent.agent.tools import SCHEMA_NUDGE, TOOL_DEFINITIONS
from ai_agent.approval.prompt import ApprovalPrompter, PendingCommand
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.ast import parse_command_expr
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.llm.base import LLMMessage, LLMProvider, ToolCall
from ai_agent.policy.engine import PolicyEngine
from ai_agent.policy.risk import RiskLevel

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    final_message: str
    iterations: int
    error: str | None = None


class AgentLoop:
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        policy: PolicyEngine,
        executor: CommandExecutor,
        audit: AuditLogger,
        prompter: ApprovalPrompter,
        session: ApprovalSession,
    ):
        self.settings = settings
        self.llm = llm
        self.policy = policy
        self.executor = executor
        self.audit = audit
        self.prompter = prompter
        self.session = session
        runtime = gather_runtime_context(settings)
        system_prompt = build_system_prompt(runtime, policy.allowed_binaries())
        self.messages: list[LLMMessage] = [
            LLMMessage(role="system", content=system_prompt)
        ]

    def run(self, user_input: str) -> AgentRunResult:
        self.messages.append(LLMMessage(role="user", content=user_input))

        for iteration in range(1, self.settings.agent_max_iterations + 1):
            response = self.llm.chat(self.messages, tools=TOOL_DEFINITIONS)
            if response.error:
                return AgentRunResult(
                    final_message=f"LLM error: {response.error}",
                    iterations=iteration,
                    error=response.error,
                )

            assistant = response.message
            self.messages.append(assistant)

            if not assistant.tool_calls:
                if iteration < self.settings.agent_max_iterations:
                    self.messages.append(LLMMessage(role="user", content=SCHEMA_NUDGE))
                    continue
                return AgentRunResult(
                    final_message=(
                        "The model stopped without calling respond(finished=true). "
                        "Try again or narrow the request."
                    ),
                    iterations=iteration,
                    error="missing_respond",
                )

            final_message = self._process_tool_calls(assistant.tool_calls)
            if final_message is not None:
                return AgentRunResult(
                    final_message=final_message,
                    iterations=iteration,
                )

        return AgentRunResult(
            final_message=(
                "Stopped after reaching the maximum number of tool iterations. "
                "Try a narrower request."
            ),
            iterations=self.settings.agent_max_iterations,
            error="max_iterations",
        )

    def _process_tool_calls(self, tool_calls: list[ToolCall]) -> str | None:
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
            self.messages.append(tool_message)
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
        pending: list[PendingCommand] = []
        call_map: list[tuple[ToolCall, object]] = []

        for call in tool_calls:
            if call.name == "run_commands":
                for command_data in call.arguments.get("commands", []):
                    expr = parse_command_expr(command_data)
                    decision = self.policy.evaluate(expr)
                    pending.append(
                        PendingCommand(
                            expr=expr,
                            decision=decision,
                            reason=call.arguments.get("reason"),
                        )
                    )
                    call_map.append((call, expr))
            elif call.name == "run_command":
                expr = parse_command_expr(call.arguments.get("command", {}))
                decision = self.policy.evaluate(expr)
                pending.append(
                    PendingCommand(
                        expr=expr,
                        decision=decision,
                        reason=call.arguments.get("reason"),
                    )
                )
                call_map.append((call, expr))

        if any(item.decision.effective_risk != RiskLevel.READ_ONLY for item in pending):
            results: list[LLMMessage] = []
            for call in tool_calls:
                results.append(self._handle_tool_call(call))
            return results

        approval = self.prompter.prompt_batch(pending)
        results: list[LLMMessage] = []
        for (call, expr), item in zip(call_map, pending, strict=True):
            result_payload = self._execute_with_audit(
                tool_name=call.name,
                arguments=call.arguments,
                expr=expr,
                decision=item.decision,
                approved=approval.approved,
            )
            results.append(
                LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(result_payload, ensure_ascii=True),
                    tool_call_id=call.id,
                )
            )
        return results

    def _handle_tool_call(self, call: ToolCall) -> LLMMessage:
        if call.name == "run_commands":
            commands = call.arguments.get("commands", [])
            pending = []
            exprs = []
            for command_data in commands:
                expr = parse_command_expr(command_data)
                decision = self.policy.evaluate(expr)
                pending.append(
                    PendingCommand(
                        expr=expr,
                        decision=decision,
                        reason=call.arguments.get("reason"),
                    )
                )
                exprs.append(expr)

            approval = self.prompter.prompt_batch(pending)
            payloads = []
            for expr, item in zip(exprs, pending, strict=True):
                payloads.append(
                    self._execute_with_audit(
                        tool_name=call.name,
                        arguments=call.arguments,
                        expr=expr,
                        decision=item.decision,
                        approved=approval.approved,
                    )
                )
            return LLMMessage(
                role="tool",
                name=call.name,
                content=json.dumps(payloads, ensure_ascii=True),
                tool_call_id=call.id,
            )

        if call.name == "run_command":
            try:
                expr = parse_command_expr(call.arguments.get("command", {}))
            except Exception as exc:
                payload = {"success": False, "error": f"Invalid command expression: {exc}"}
                return LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                )

            decision = self.policy.evaluate(expr)
            auto = self.prompter.should_auto_run(decision)
            if auto:
                approval_granted = True
            else:
                approval = self.prompter.prompt_single(
                    decision,
                    reason=call.arguments.get("reason"),
                )
                approval_granted = approval.approved

            payload = self._execute_with_audit(
                tool_name=call.name,
                arguments=call.arguments,
                expr=expr,
                decision=decision,
                approved=approval_granted,
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

    def _execute_with_audit(
        self,
        *,
        tool_name: str,
        arguments: dict,
        expr,
        decision,
        approved: bool,
    ) -> dict:
        confirmation_required = not self.prompter.should_auto_run(decision)
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
            )
            return payload

        result = self.executor.run(expr)
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
        )
        return payload
