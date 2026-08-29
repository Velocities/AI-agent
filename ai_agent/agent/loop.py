from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from ai_agent.agent.context import build_system_prompt, gather_runtime_context
from ai_agent.agent.tools import CONTINUE_NUDGE, SCHEMA_NUDGE, TOOL_DEFINITIONS
from ai_agent.approval.prompt import ApprovalPrompter, PendingCommand
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.ast import parse_command_expr
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.llm.base import LLMErrorKind, LLMMessage, LLMProvider, LLMResponse, ToolCall
from ai_agent.llm.streaming import (
    RespondMessageStreamer,
    ResumeOverlapTrimmer,
    trim_resume_overlap,
)
from ai_agent.policy.engine import PolicyEngine
from ai_agent.policy.risk import RiskLevel

logger = logging.getLogger(__name__)

_RECOVERABLE_TRUNCATION_KINDS = frozenset(
    {
        LLMErrorKind.STREAM_INTERRUPTED,
        LLMErrorKind.STREAM_INCOMPLETE,
    }
)


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

    def warmup(self) -> tuple[bool, str, float]:
        """Load the model with the agent system prompt and tool schema."""
        import time

        logger.info(
            "Warming up model with agent context (system prompt + %d tools)",
            len(TOOL_DEFINITIONS),
        )
        start = time.perf_counter()
        response = self.llm.chat(
            [
                self.messages[0],
                LLMMessage(
                    role="user",
                    content="Startup warmup. Reply with the single word: ready",
                ),
            ],
            tools=TOOL_DEFINITIONS,
        )
        duration = time.perf_counter() - start

        if response.error:
            logger.warning("Model warmup failed after %.1fs: %s", duration, response.error)
            return False, response.error, duration

        logger.info(
            "Model warmup complete in %.1fs (loaded with agent context)",
            duration,
        )
        return True, "ready", duration

    def run(
        self,
        user_input: str,
        *,
        stream_callback: Callable[[str], None] | None = None,
        iteration_callback: Callable[[int], None] | None = None,
        notice_callback: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        self.messages.append(LLMMessage(role="user", content=user_input))

        for iteration in range(1, self.settings.agent_max_iterations + 1):
            if iteration_callback is not None:
                iteration_callback(iteration)
            response = self._generate_assistant_turn(stream_callback, notice_callback)

            assistant = response.message
            partial = (assistant.content or "").strip()

            if response.error:
                return AgentRunResult(
                    final_message=partial or f"LLM error: {response.error}",
                    iterations=iteration,
                    error=response.error,
                )

            self.messages.append(assistant)

            if self._was_cut_short(response):
                return AgentRunResult(
                    final_message=partial,
                    iterations=iteration,
                    error="truncated",
                )

            if not assistant.tool_calls:
                answer = (assistant.content or "").strip()
                if answer:
                    return AgentRunResult(
                        final_message=answer,
                        iterations=iteration,
                    )
                if iteration < self.settings.agent_max_iterations:
                    self.messages.append(LLMMessage(role="user", content=SCHEMA_NUDGE))
                    continue
                return AgentRunResult(
                    final_message=(
                        "The model produced no answer and called no tools. "
                        "Try again or narrow the request."
                    ),
                    iterations=iteration,
                    error="empty_response",
                )

            if stream_callback is not None and (assistant.content or "").strip():
                stream_callback("\n\n")

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

    def _generate_assistant_turn(
        self,
        stream_callback: Callable[[str], None] | None,
        notice_callback: Callable[[str], None] | None,
    ) -> LLMResponse:
        """Produce one complete assistant turn, resuming if the model is cut off.

        Being cut off by a token or context limit is an infrastructure event, not
        the model deciding it is done, so the answer is resumed transparently.
        """
        streaming = stream_callback is not None and self.settings.agent_stream_responses
        attempts = max(1, self.settings.agent_max_continuations + 1)
        fragments: list[str] = []
        response = LLMResponse(
            message=LLMMessage(role="assistant", content=""),
            error="LLM produced no response.",
        )
        cut_short = False

        for _attempt in range(attempts):
            produced = "".join(fragments)
            resume_tail = produced[-self.settings.agent_continuation_tail :]
            messages = self._resume_messages(resume_tail) if produced else self.messages

            if streaming:
                response = self._chat_with_stream(
                    messages,
                    stream_callback,
                    notice_callback,
                    resume_tail=resume_tail,
                )
            else:
                response = self.llm.chat(messages, tools=TOOL_DEFINITIONS)

            content = response.message.content or ""
            if resume_tail:
                content = trim_resume_overlap(resume_tail, content)
            fragments.append(content)

            cut_short = self._was_cut_short(response)
            if not cut_short:
                break
            logger.debug(
                "Resuming answer cut short by %s",
                response.stop_reason or response.error,
            )

        return LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="".join(fragments),
                tool_calls=response.message.tool_calls,
            ),
            done=response.done,
            model=response.model,
            # A cut-off stream is reported through stop_reason, not as an error,
            # so an exhausted resume budget keeps the text produced so far.
            error=None if cut_short else response.error,
            error_kind=None if cut_short else response.error_kind,
            stop_reason="length" if cut_short else response.stop_reason,
        )

    def _resume_messages(self, resume_tail: str) -> list[LLMMessage]:
        """Prompt for resuming a cut-off answer.

        Only the tail of the partial answer is resent so the prompt stays a
        constant size; regrowing it each attempt is what exhausts the context
        window and makes the model restart from the beginning.
        """
        return [
            *self.messages,
            LLMMessage(role="assistant", content=resume_tail),
            LLMMessage(role="user", content=CONTINUE_NUDGE),
        ]

    def _chat_with_stream(
        self,
        messages: list[LLMMessage],
        stream_callback: Callable[[str], None],
        notice_callback: Callable[[str], None] | None = None,
        *,
        resume_tail: str = "",
    ) -> LLMResponse:
        streamer = RespondMessageStreamer()
        trimmer = ResumeOverlapTrimmer(resume_tail)
        response: LLMResponse | None = None
        active_tool_name: str | None = None
        streamed_content = ""

        def emit(text: str) -> None:
            visible = trimmer.feed(text)
            if visible:
                stream_callback(visible)

        for chunk in self.llm.chat_stream(messages, tools=TOOL_DEFINITIONS):
            if chunk.content_delta:
                emit(chunk.content_delta)
                streamed_content += chunk.content_delta
            if chunk.tool_name:
                active_tool_name = chunk.tool_name
            if chunk.tool_arguments_delta and active_tool_name == "respond":
                text = streamer.feed(chunk.tool_arguments_delta)
                if text:
                    emit(text)
            if chunk.done and chunk.response is not None:
                response = chunk.response

        if response is not None:
            self._emit_unstreamed_content(response, streamed_content, emit)

            for call in response.message.tool_calls:
                if call.name != "respond":
                    continue
                message = call.arguments.get("message", "")
                if not isinstance(message, str):
                    message = ""
                if call.arguments.get("finished") is True:
                    remaining = streamer.flush_message(message)
                    if remaining:
                        emit(remaining)
                elif message and notice_callback is not None:
                    notice_callback(message)

            trailing = streamer.flush_message()
            if trailing:
                emit(trailing)

        buffered = trimmer.flush()
        if buffered:
            stream_callback(buffered)

        if response is None:
            return LLMResponse(
                message=LLMMessage(role="assistant", content=""),
                error="LLM stream ended without a response.",
            )
        return response

    @staticmethod
    def _emit_unstreamed_content(
        response: LLMResponse,
        streamed_content: str,
        emit: Callable[[str], None],
    ) -> None:
        """Show content that arrived only in the final chunk.

        Providers that cannot stream deliver the whole answer at the end. The
        prefix check keeps that from reprinting text already streamed when a
        provider's final content does not match the deltas exactly.
        """
        final_content = response.message.content or ""
        if not final_content or final_content == streamed_content:
            return
        if not streamed_content:
            emit(final_content)
            return
        if final_content.startswith(streamed_content):
            emit(final_content[len(streamed_content) :])
            return
        logger.debug("Final content diverged from streamed deltas; skipping flush")

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
                commands = call.arguments.get("commands", [])
                if not isinstance(commands, list):
                    return [self._handle_tool_call(item) for item in tool_calls]
                for command_data in commands:
                    try:
                        expr = parse_command_expr(command_data)
                    except Exception:
                        return [self._handle_tool_call(item) for item in tool_calls]
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
                try:
                    expr = parse_command_expr(call.arguments.get("command", {}))
                except Exception:
                    return [self._handle_tool_call(item) for item in tool_calls]
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
            if not isinstance(commands, list):
                payload = {
                    "success": False,
                    "error": "commands must be an array of command expressions",
                }
                return LLMMessage(
                    role="tool",
                    name=call.name,
                    content=json.dumps(payload, ensure_ascii=True),
                    tool_call_id=call.id,
                )

            parsed: list[object | str] = []
            pending = []
            for command_data in commands:
                try:
                    expr = parse_command_expr(command_data)
                except Exception as exc:
                    parsed.append(f"Invalid command expression: {exc}")
                    continue
                parsed.append(expr)
                pending.append(
                    PendingCommand(
                        expr=expr,
                        decision=self.policy.evaluate(expr),
                        reason=call.arguments.get("reason"),
                    )
                )

            approval = self.prompter.prompt_batch(pending) if pending else None
            payloads = []
            pending_iter = iter(pending)
            for item in parsed:
                if isinstance(item, str):
                    payloads.append({"success": False, "error": item})
                    continue
                pending_item = next(pending_iter)
                payloads.append(
                    self._execute_with_audit(
                        tool_name=call.name,
                        arguments=call.arguments,
                        expr=item,
                        decision=pending_item.decision,
                        approved=approval.approved if approval else False,
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

    @staticmethod
    def _was_cut_short(response: LLMResponse) -> bool:
        """True when generation stopped for a limit rather than being finished."""
        if response.stop_reason == "length":
            return AgentLoop._has_generation_output(response.message)
        if response.error_kind in _RECOVERABLE_TRUNCATION_KINDS:
            return AgentLoop._has_generation_output(response.message)
        return False

    @staticmethod
    def _has_generation_output(message: LLMMessage) -> bool:
        if (message.content or "").strip():
            return True
        for call in message.tool_calls:
            if call.name != "respond":
                continue
            if call.arguments.get("message"):
                return True
            if call.arguments.get("_malformed"):
                return True
        return False
