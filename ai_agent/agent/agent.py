from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from ai_agent.agent.assistant import AssistantGenerator
from ai_agent.agent.command_parse import (
    coerce_command_list,
    parse_command_structure,
    policy_decision,
    resolve_target,
)
from ai_agent.agent.context import (
    RuntimeContext,
    append_personalization,
    build_system_prompt,
    gather_runtime_context,
)
from ai_agent.agent.tool_result import (
    failure_message,
    latest_tool_error,
    policy_rejection,
    record_command_audit,
    respond_result,
    run_command,
    tool_message,
    user_rejection,
    workflow_tool_result,
)
from ai_agent.agent.tools import (
    COMMAND_DUMP_NUDGE,
    SCHEMA_NUDGE,
    build_tool_definitions,
    looks_like_command_dump,
    looks_like_named_tool_dump,
    parse_dumped_tool_call,
)
from ai_agent.agent.warmup import warmup_llm
from ai_agent.approval.prompt import ApprovalPrompter, ApprovalResult, PendingCommand
from ai_agent.approval.selection import (
    apply_batch_approval,
    approval_flags,
    batch_ordering,
    order_groups_for,
)
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.ast import CommandExpr, SingleCommand
from ai_agent.commands.executor import CommandExecutor
from ai_agent.commands.render import render_command
from ai_agent.config import Settings
from ai_agent.conversations.personalization import UserPreferences
from ai_agent.execution_targets.base import ExecutionTarget, UnknownExecutionTarget
from ai_agent.execution_targets.router import ExecutionTargetRouter
from ai_agent.execution_targets.workflow import WORKFLOW_TARGET_NAME, WorkflowExecutionTarget
from ai_agent.llm.base import ImageInput, LLMErrorKind, LLMMessage, LLMProvider, ToolCall
from ai_agent.policy.engine import PolicyDecision, PolicyEngine
from ai_agent.workflows.manifests import WorkflowError, validate_tool_input
from ai_agent.workflows.prompt import append_workflow_prompt
from ai_agent.workflows.session import WorkflowSession

logger = logging.getLogger(__name__)


@dataclass
class AgentCancelled(Exception):
    """The client went away while a turn was still running."""


@dataclass
class AgentRunResult:
    final_message: str
    iterations: int
    error: str | None = None
    error_kind: LLMErrorKind | None = None


class Agent:
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        policy: PolicyEngine,
        executor: CommandExecutor,
        audit: AuditLogger,
        prompter: ApprovalPrompter,
        session: ApprovalSession,
        router: ExecutionTargetRouter | None = None,
        runtime_context: RuntimeContext | None = None,
        personalization: UserPreferences | None = None,
        workflow_session: WorkflowSession | None = None,
    ):
        self.settings = settings
        self.llm = llm
        self.policy = policy
        self.executor = executor
        self.router = router or ExecutionTargetRouter.local_only(executor)
        self.audit = audit
        self.prompter = prompter
        self.session = session
        self.workflow_session = workflow_session
        self.workflow = None if workflow_session is None else workflow_session.manifest
        tool_names = None
        if workflow_session is not None:
            tool_names = [tool.name for tool in workflow_session.manifest.tools]
        self.tool_definitions = build_tool_definitions(
            self.router.names(),
            workflow_tool_names=tool_names,
        )
        runtime = runtime_context or gather_runtime_context(settings)
        system_prompt = append_workflow_prompt(
            append_personalization(
                build_system_prompt(
                    runtime,
                    policy.allowed_binaries(),
                    self.router.summaries(),
                    default_target=self.router.default_name,
                    unlisted_need_approval=policy.unlisted_need_approval(),
                ),
                personalization,
            ),
            workflow_session,
        )
        self.messages: list[LLMMessage] = [
            LLMMessage(role="system", content=system_prompt)
        ]
        self.on_message: Callable[[LLMMessage], None] | None = None
        self.should_stop: Callable[[], bool] | None = None
        self.assistant = AssistantGenerator(llm, settings, self.tool_definitions)

    def warmup(self) -> tuple[bool, str, float]:
        """Load the model with the agent system prompt and tool schema."""
        return warmup_llm(
            self.llm,
            self.messages[0].content,
            tools=self.tool_definitions,
        )

    def answer_user(
        self,
        user_input: str,
        *,
        stream_callback: Callable[[str], None] | None = None,
        iteration_callback: Callable[[int], None] | None = None,
        notice_callback: Callable[[str], None] | None = None,
        images: list[ImageInput] | None = None,
    ) -> AgentRunResult:
        return self.forward_user_input(
            user_input,
            images,
            stream_callback=stream_callback,
            iteration_callback=iteration_callback,
            notice_callback=notice_callback,
        )

    def forward_user_input(
        self,
        input_text: str,
        attachments: list[ImageInput] | None = None,
        *,
        stream_callback: Callable[[str], None] | None = None,
        iteration_callback: Callable[[int], None] | None = None,
        notice_callback: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        """Ask the model, then parse, check policy, ask permission, and run.

        This method is the only place that orders those stages. Each helper
        returns a result and does not call the next stage itself.
        """
        self.remember_message(
            LLMMessage(
                role="user",
                content=input_text,
                images=list(attachments or []),
            )
        )
        recent_tool_errors: list[str] = []
        dump_recoveries = 0
        logger.info(
            "Turn start model=%s input=%r",
            getattr(self.llm, "model_name", "") or self.settings.llm_model,
            input_text[:200],
        )

        def notice(text: str) -> None:
            logger.info("%s", text)
            if notice_callback is not None:
                notice_callback(text)

        for iteration in range(1, self.settings.agent_max_iterations + 1):
            self.raise_if_stopped()
            if iteration_callback is not None:
                iteration_callback(iteration)
            logger.info("Iteration %s: asking model", iteration)
            # Let the model read the conversation and either answer or call tools
            response = self.assistant.generate_turn(
                self.messages, stream_callback, notice_callback
            )
            assistant = response.message
            partial = (assistant.content or "").strip()
            logger.info(
                "Iteration %s: content_chars=%s tools=%s stop=%s error=%s",
                iteration,
                len(partial),
                [call.name for call in assistant.tool_calls] or None,
                response.stop_reason,
                response.error,
            )
            if response.error:
                return AgentRunResult(
                    final_message=partial or f"LLM error: {response.error}",
                    iterations=iteration,
                    error=response.error,
                    error_kind=response.error_kind,
                )
            self.remember_message(assistant)
            if self.assistant.was_cut_short(response):
                return AgentRunResult(
                    final_message=partial,
                    iterations=iteration,
                    error="truncated",
                )
            if not assistant.tool_calls:
                # Weaker models print a tool call as text. Promote it, or treat
                # the text as the final answer when it is not a call.
                recovered = self.recover_printed_tool_call(
                    assistant, iteration, dump_recoveries, notice
                )
                if isinstance(recovered, AgentRunResult):
                    return recovered
                if recovered == "nudge":
                    continue
                if recovered == "promoted":
                    dump_recoveries += 1
            if stream_callback is not None and (assistant.content or "").strip():
                stream_callback("\n\n")
            logger.info(
                "Iteration %s: executing tools %s",
                iteration,
                [call.name for call in assistant.tool_calls],
            )
            # Parse, check policy, ask permission, then run or report a rejection
            final_message = self.handle_tool_calls(assistant.tool_calls)
            if final_message is not None:
                logger.info("Iteration %s: tool path returned final message", iteration)
                return AgentRunResult(final_message=final_message, iterations=iteration)
            # Stop if the model keeps hitting the same tool error. A success clears the streak.
            error_signature = latest_tool_error(self.messages)
            if error_signature:
                recent_tool_errors.append(error_signature)
                notice(f"Tool error: {error_signature[:180]}")
                if (
                    len(recent_tool_errors) >= 3
                    and len(set(recent_tool_errors[-3:])) == 1
                ):
                    logger.error("Stopping after repeated tool error: %s", error_signature)
                    return AgentRunResult(
                        final_message=(
                            "Stopped after the same tool error repeated three times. "
                            f"Last error: {error_signature}"
                        ),
                        iterations=iteration,
                        error="repeated_tool_error",
                    )
            else:
                recent_tool_errors.clear()
                dump_recoveries = 0

        logger.error("Hit max tool iterations (%s)", self.settings.agent_max_iterations)
        return AgentRunResult(
            final_message=(
                "Stopped after reaching the maximum number of tool iterations. "
                "Try a narrower request."
            ),
            iterations=self.settings.agent_max_iterations,
            error="max_iterations",
        )

    def recover_printed_tool_call(
        self,
        assistant: LLMMessage,
        iteration: int,
        dump_recoveries: int,
        notice: Callable[[str], None],
    ) -> str | AgentRunResult | None:
        """Promote a printed tool call, nudge the model, or accept a real answer"""
        answer = (assistant.content or "").strip()
        recovered = parse_dumped_tool_call(answer) if answer else None
        if recovered is not None and dump_recoveries < 2:
            notice(
                f"Recovered printed tool call as {recovered.name} "
                f"(attempt {dump_recoveries + 1})"
            )
            assistant.tool_calls = [recovered]
            assistant.content = ""
            return "promoted"
        if answer and (looks_like_named_tool_dump(answer) or looks_like_command_dump(answer)):
            logger.warning("Iteration %s: unrecoverable tool dump; nudging model", iteration)
            if iteration < self.settings.agent_max_iterations:
                self.remember_message(LLMMessage(role="user", content=COMMAND_DUMP_NUDGE))
                return "nudge"
            return AgentRunResult(
                final_message=(
                    "The model printed a tool call as text instead of "
                    "invoking it, and could not recover. Try again."
                ),
                iterations=iteration,
                error="tool_dump",
            )
        if answer:
            logger.info("Iteration %s: final text answer (%s chars)", iteration, len(answer))
            return AgentRunResult(final_message=answer, iterations=iteration)
        if iteration < self.settings.agent_max_iterations:
            logger.warning("Iteration %s: empty model output; schema nudge", iteration)
            self.remember_message(LLMMessage(role="user", content=SCHEMA_NUDGE))
            return "nudge"
        return AgentRunResult(
            final_message=(
                "The model produced no answer and called no tools. "
                "Try again or narrow the request."
            ),
            iterations=iteration,
            error="empty_response",
        )

    def handle_tool_calls(self, tool_calls: list[ToolCall]) -> str | None:
        # Several command calls in one turn share a single permission question.
        # Anything mixed with respond or run_tool is handled one call at a time.
        command_calls = [
            call for call in tool_calls if call.name in {"run_command", "run_commands"}
        ]
        other_calls = [
            call for call in tool_calls if call.name not in {"run_command", "run_commands"}
        ]
        if len(command_calls) > 1 and not other_calls:
            messages = self.handle_command_batch(command_calls)
        else:
            messages = []
            final_message = None
            for call in tool_calls:
                if call.name == "respond":
                    # finished=True is the answer the user sees. The loop stops.
                    message, finished = respond_result(call)
                    messages.append(message)
                    if finished is not None:
                        final_message = finished
                else:
                    messages.append(self.handle_one_call(call))
            for message in messages:
                self.remember_message(message)
            return final_message
        for message in messages:
            self.remember_message(message)
        return None

    def handle_one_call(self, call: ToolCall) -> LLMMessage:
        if call.name == "run_tool":
            return self.handle_run_tool(call)
        if call.name == "run_commands":
            return self.handle_run_commands(call)
        if call.name == "run_command":
            return self.handle_run_command(call)
        return failure_message(call, f"Unknown tool: {call.name}")

    def handle_run_command(self, call: ToolCall) -> LLMMessage:
        # Turn the model's JSON into a command tree. A bad shape never reaches policy.
        expr, parse_error = parse_command_structure(call.arguments.get("command", {}))
        if parse_error or expr is None:
            return failure_message(call, parse_error or "Invalid command expression")
        # Pick the machine this command runs on
        target_name, target, target_error = resolve_target(self.router, call.arguments)
        if target_error:
            return failure_message(call, target_error)
        # Check if the model's command is allowed, and whether it is safe enough
        # to auto-approve without the user
        decision = policy_decision(self.policy, expr, target)
        allowed = self.permission_for_one(call, decision, target)
        # Tell the model it was rejected, or run the command and send the output back
        payload = self.outcome_for(
            call.name, call.arguments, expr, decision, allowed, target_name, target
        )
        return tool_message(call, payload)

    def handle_run_commands(self, call: ToolCall) -> LLMMessage:
        # One permission question for the list. A command that does not parse is
        # one failed entry; the others still run.
        commands, commands_error = coerce_command_list(call.arguments.get("commands", []))
        if commands_error or commands is None:
            logger.warning("run_commands coerce failed: %s", commands_error)
            return failure_message(call, commands_error or "commands must be an array")
        call.arguments["commands"] = commands
        ordering, ordering_error = batch_ordering(call.arguments)
        if ordering_error:
            return failure_message(call, ordering_error)
        target_name, target, target_error = resolve_target(self.router, call.arguments)
        if target_error:
            return failure_message(call, target_error)
        prepared = self.prepare_batch(commands, call.arguments, target)
        pending = [item.pending for item in prepared if item.pending is not None]
        approval, flags = self.permission_for_batch(pending, ordering, target)
        flag_iter = iter(flags)
        payloads: list[dict] = []
        decided: list[dict] = []
        for item in prepared:
            if item.error is not None or item.expr is None or item.pending is None:
                payloads.append({"success": False, "error": item.error})
                continue
            payload = self.outcome_for(
                call.name,
                call.arguments,
                item.expr,
                item.pending.decision,
                next(flag_iter),
                target_name,
                target,
            )
            payloads.append(payload)
            decided.append(payload)
        if approval is not None:
            # Tell the model which commands in this list the user accepted
            apply_batch_approval(
                decided,
                accepted=approval.accepted,
                cascade_rejected=approval.cascade_rejected,
            )
        return tool_message(call, payloads)

    def handle_command_batch(self, tool_calls: list[ToolCall]) -> list[LLMMessage]:
        """One permission prompt for several command calls.

        One tool message is returned per command. A call that does not parse,
        or names an unknown target, drops the shared prompt and each call is
        handled on its own.
        """
        pending: list[PendingCommand] = []
        call_map: list[tuple[ToolCall, CommandExpr, str, ExecutionTarget | None]] = []
        groups: list[int | None] = []
        next_group = 0
        for call in tool_calls:
            if call.name == "run_commands":
                commands, commands_error = coerce_command_list(
                    call.arguments.get("commands", [])
                )
                if commands_error or commands is None:
                    return [self.handle_one_call(item) for item in tool_calls]
                call.arguments["commands"] = commands
                ordering, ordering_error = batch_ordering(call.arguments)
                if ordering_error:
                    return [self.handle_one_call(item) for item in tool_calls]
                group: int | None = None
                if ordering == "ordered":
                    group = next_group
                    next_group += 1
                target_name = ""
                target: ExecutionTarget | None = None
                if commands:
                    target_name, target, target_error = resolve_target(
                        self.router, call.arguments
                    )
                    if target_error:
                        return [self.handle_one_call(item) for item in tool_calls]
                prepared = self.prepare_batch(commands, call.arguments, target)
                if any(item.error for item in prepared):
                    return [self.handle_one_call(item) for item in tool_calls]
                for item in prepared:
                    assert item.expr is not None and item.pending is not None
                    pending.append(item.pending)
                    call_map.append((call, item.expr, target_name, target))
                    groups.append(group)
            elif call.name == "run_command":
                expr, parse_error = parse_command_structure(
                    call.arguments.get("command", {})
                )
                if parse_error or expr is None:
                    return [self.handle_one_call(item) for item in tool_calls]
                target_name, target, target_error = resolve_target(
                    self.router, call.arguments
                )
                if target_error:
                    return [self.handle_one_call(item) for item in tool_calls]
                # Included in the one shared prompt only after policy has a decision
                decision = policy_decision(self.policy, expr, target)
                pending.append(
                    self.pending_command(expr, decision, call.arguments, target)
                )
                call_map.append((call, expr, target_name, target))
                groups.append(None)
        # Isolated workflow containers skip the host prompt. Every command may run.
        workflow_batch = all(
            target is not None and not target.uses_host_policy
            for _call, _expr, _target_name, target in call_map
        )
        if workflow_batch:
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
                self.outcome_for(
                    call.name,
                    call.arguments,
                    expr,
                    item.decision,
                    flags[index],
                    target_name,
                    target,
                )
            )
        if approval is not None:
            apply_batch_approval(
                payloads,
                accepted=approval.accepted,
                cascade_rejected=approval.cascade_rejected,
            )
        return [
            tool_message(call, payload)
            for payload, (call, _expr, _target_name, _target) in zip(
                payloads, call_map, strict=True
            )
        ]

    def handle_run_tool(self, call: ToolCall) -> LLMMessage:
        # The entrypoint comes from the workflow manifest, not from the model.
        # Host policy does not apply inside the workflow container.
        if self.workflow is None:
            return failure_message(call, "run_tool is only available inside a workflow session")
        name = call.arguments.get("tool")
        raw_input = call.arguments.get("input")
        if not isinstance(name, str):
            return failure_message(call, "tool must be a workflow tool name")
        try:
            tool = self.workflow.tool(name)
            validate_tool_input(tool, raw_input)
        except WorkflowError as exc:
            return failure_message(call, str(exc))
        try:
            target = self.router.resolve(WORKFLOW_TARGET_NAME)
        except UnknownExecutionTarget as exc:
            return failure_message(call, str(exc))
        if not isinstance(target, WorkflowExecutionTarget):
            return failure_message(call, "run_tool requires the workflow execution target")
        expr = SingleCommand(argv=[tool.entrypoint])
        decision = policy_decision(self.policy, expr, target)
        payload = self.outcome_for(
            call.name,
            call.arguments,
            expr,
            decision,
            True,
            target.name,
            target,
            runner=lambda: target.run_tool(tool.entrypoint, json.dumps(raw_input)),
        )
        # Give the model the parsed tool JSON, not the container's raw stdout
        return tool_message(call, workflow_tool_result(payload, tool))

    def permission_for_one(
        self,
        call: ToolCall,
        decision: PolicyDecision,
        target: ExecutionTarget | None,
    ) -> bool:
        # The container is isolated, so there is nothing on the host to approve
        if target is not None and not target.uses_host_policy:
            return True
        # Policy already forbade it. Do not ask the user to override that.
        if not decision.allowed:
            return False
        # Safe enough for this confirmation mode to run without asking
        if not self.prompter.needs_user(decision):
            return True
        approval = self.prompter.ask(
            decision,
            reason=call.arguments.get("reason"),
            target_display=target.display() if target else None,
            target_name=target.name if target else None,
            target_kind=target.kind if target else None,
        )
        return approval.approved

    def permission_for_batch(
        self,
        pending: list[PendingCommand],
        ordering: str,
        target: ExecutionTarget | None,
    ) -> tuple[ApprovalResult | None, list[bool]]:
        # One yes/no for the whole list. Each flag says whether that command may run.
        if target is not None and not target.uses_host_policy:
            return None, [True] * len(pending)
        if not pending:
            return None, []
        approval = self.prompter.prompt_batch(
            pending,
            order_groups=order_groups_for(ordering, len(pending)),
        )
        return approval, approval_flags(approval.approved, approval.accepted, len(pending))

    def outcome_for(
        self,
        tool_name: str,
        arguments: dict,
        expr: CommandExpr,
        decision: PolicyDecision,
        allowed: bool,
        target_name: str,
        target: ExecutionTarget | None,
        runner: Callable[[], object] | None = None,
    ) -> dict:
        """Tell the model the policy or user said no, or return the process output.

        run_command only starts the process. The choice to run it was already made.
        """
        skip_prompt = target is not None and not target.uses_host_policy
        confirmation_required = not skip_prompt and not self.prompter.should_auto_run(decision)
        if not decision.allowed:
            logger.warning(
                "Policy denied %s on %s: %s",
                tool_name,
                target_name,
                decision.reason,
            )
            payload = policy_rejection(decision)
            self.record_outcome(
                tool_name,
                arguments,
                decision,
                confirmation_required,
                False,
                payload,
                decision.reason,
                target_name,
            )
        elif not allowed:
            logger.info("User denied %s on %s", tool_name, target_name)
            payload = user_rejection()
            self.record_outcome(
                tool_name,
                arguments,
                decision,
                confirmation_required,
                False,
                payload,
                "user_denied",
                target_name,
            )
        else:
            payload = run_command(target, expr, target_name, runner)
            # An unknown target is an error for the model, and is not an audited run
            if target is not None:
                self.record_outcome(
                    tool_name,
                    arguments,
                    decision,
                    confirmation_required,
                    True,
                    payload,
                    None,
                    target_name,
                )
        payload.setdefault("rendered_command", render_command(expr))
        payload["execution_target"] = {
            "name": target_name,
            "kind": target.kind if target is not None else None,
        }
        return payload

    def prepare_batch(self, commands: list, arguments: dict, target: ExecutionTarget | None):
        prepared = []
        for command_data in commands:
            expr, parse_error = parse_command_structure(command_data)
            if parse_error or expr is None:
                prepared.append(PreparedCommand(expr=None, pending=None, error=parse_error))
                continue
            # Check if this command is allowed, and whether it is safe enough
            # to auto-approve without the user
            decision = policy_decision(self.policy, expr, target)
            prepared.append(
                PreparedCommand(
                    expr=expr,
                    pending=self.pending_command(expr, decision, arguments, target),
                    error=None,
                )
            )
        return prepared

    def pending_command(
        self,
        expr: CommandExpr,
        decision: PolicyDecision,
        arguments: dict,
        target: ExecutionTarget | None,
    ) -> PendingCommand:
        return PendingCommand(
            expr=expr,
            decision=decision,
            reason=arguments.get("reason"),
            target_display=target.display() if target else None,
            target_name=target.name if target else None,
            target_kind=target.kind if target else None,
        )

    def record_outcome(
        self,
        tool_name: str,
        arguments: dict,
        decision: PolicyDecision,
        confirmation_required: bool,
        confirmation_granted: bool,
        result: dict,
        error: str | None,
        execution_target: str,
    ) -> None:
        record_command_audit(
            self.audit,
            session_id=self.session.session_id,
            tool_name=tool_name,
            arguments=arguments,
            decision=decision,
            confirmation_required=confirmation_required,
            confirmation_granted=confirmation_granted,
            result=result,
            error=error,
            execution_target=execution_target,
        )

    def remember_message(self, message: LLMMessage) -> None:
        self.raise_if_stopped()
        self.messages.append(message)
        if self.on_message is not None:
            self.on_message(message)

    def raise_if_stopped(self) -> None:
        if self.should_stop is not None and self.should_stop():
            raise AgentCancelled()


@dataclass
class PreparedCommand:
    expr: CommandExpr | None
    pending: PendingCommand | None
    error: str | None
