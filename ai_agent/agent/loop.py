from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ai_agent.agent.tools import SYSTEM_PROMPT, TOOL_DEFINITIONS
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
        self.messages: list[LLMMessage] = [
            LLMMessage(role="system", content=SYSTEM_PROMPT)
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
                return AgentRunResult(
                    final_message=assistant.content or "(empty response)",
                    iterations=iteration,
                )

            tool_calls = assistant.tool_calls
            if len(tool_calls) > 1 and all(
                call.name in {"run_command", "run_commands"} for call in tool_calls
            ):
                batch_results = self._handle_batch_tool_calls(tool_calls)
            else:
                batch_results = []
                for call in tool_calls:
                    batch_results.append(self._handle_tool_call(call))

            for tool_message in batch_results:
                self.messages.append(tool_message)

        return AgentRunResult(
            final_message=(
                "Stopped after reaching the maximum number of tool iterations. "
                "Try a narrower request."
            ),
            iterations=self.settings.agent_max_iterations,
            error="max_iterations",
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
