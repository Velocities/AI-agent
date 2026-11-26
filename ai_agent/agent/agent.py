from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from ai_agent.agent.assistant import AssistantGenerator
from ai_agent.agent.context import (
    RuntimeContext,
    append_personalization,
    build_system_prompt,
    gather_runtime_context,
)
from ai_agent.agent.tool_handler import ToolHandler
from ai_agent.agent.tools import (
    COMMAND_DUMP_NUDGE,
    SCHEMA_NUDGE,
    build_tool_definitions,
    looks_like_command_dump,
    looks_like_named_tool_dump,
    parse_dumped_tool_call,
)
from ai_agent.agent.warmup import warmup_llm
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.conversations.personalization import UserPreferences
from ai_agent.execution_targets.router import ExecutionTargetRouter
from ai_agent.llm.base import ImageInput, LLMErrorKind, LLMMessage, LLMProvider
from ai_agent.policy.engine import PolicyEngine
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


def _latest_tool_error_signature(messages: list[LLMMessage]) -> str | None:
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
        self._assistant = AssistantGenerator(llm, settings, self.tool_definitions)
        self._tools = ToolHandler(
            policy,
            prompter,
            self.router,
            audit,
            session,
            workflow=None if workflow_session is None else workflow_session.manifest,
        )

    def warmup(self) -> tuple[bool, str, float]:
        """Load the model with the agent system prompt and tool schema."""
        return warmup_llm(
            self.llm,
            self.messages[0].content,
            tools=self.tool_definitions,
        )

    def _raise_if_stopped(self) -> None:
        if self.should_stop is not None and self.should_stop():
            raise AgentCancelled()

    def _append(self, message: LLMMessage) -> None:
        self._raise_if_stopped()
        self.messages.append(message)
        if self.on_message is not None:
            self.on_message(message)

    def answer_user(
        self,
        user_input: str,
        *,
        stream_callback: Callable[[str], None] | None = None,
        iteration_callback: Callable[[int], None] | None = None,
        notice_callback: Callable[[str], None] | None = None,
        images: list[ImageInput] | None = None,
    ) -> AgentRunResult:
        self._append(
            LLMMessage(
                role="user",
                content=user_input,
                images=list(images or []),
            )
        )

        recent_tool_errors: list[str] = []
        dump_recoveries = 0
        logger.info(
            "Turn start model=%s input=%r",
            getattr(self.llm, "model_name", "") or self.settings.llm_model,
            user_input[:200],
        )

        def _notice(text: str) -> None:
            logger.info("%s", text)
            if notice_callback is not None:
                notice_callback(text)

        for iteration in range(1, self.settings.agent_max_iterations + 1):
            self._raise_if_stopped()
            if iteration_callback is not None:
                iteration_callback(iteration)
            logger.info("Iteration %s: asking model", iteration)
            response = self._assistant._generate_assistant_turn(
                self.messages, stream_callback, notice_callback
            )

            assistant = response.message
            partial = (assistant.content or "").strip()
            tool_names = [call.name for call in assistant.tool_calls]
            logger.info(
                "Iteration %s: content_chars=%s tools=%s stop=%s error=%s",
                iteration,
                len(partial),
                tool_names or None,
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

            self._append(assistant)

            if self._assistant._was_cut_short(response):
                return AgentRunResult(
                    final_message=partial,
                    iterations=iteration,
                    error="truncated",
                )

            if not assistant.tool_calls:
                answer = (assistant.content or "").strip()
                recovered = parse_dumped_tool_call(answer) if answer else None
                if recovered is not None and dump_recoveries < 2:
                    # llama3.1 and similar often print the call as JSON text.
                    # Promote it to a real tool call and keep going.
                    _notice(
                        f"Recovered printed tool call as {recovered.name} "
                        f"(attempt {dump_recoveries + 1})"
                    )
                    assistant.tool_calls = [recovered]
                    assistant.content = ""
                    dump_recoveries += 1
                elif answer and (
                    looks_like_named_tool_dump(answer)
                    or looks_like_command_dump(answer)
                ):
                    logger.warning(
                        "Iteration %s: unrecoverable tool dump; nudging model",
                        iteration,
                    )
                    if iteration < self.settings.agent_max_iterations:
                        self._append(
                            LLMMessage(role="user", content=COMMAND_DUMP_NUDGE)
                        )
                        continue
                    return AgentRunResult(
                        final_message=(
                            "The model printed a tool call as text instead of "
                            "invoking it, and could not recover. Try again."
                        ),
                        iterations=iteration,
                        error="tool_dump",
                    )
                elif answer:
                    logger.info(
                        "Iteration %s: final text answer (%s chars)",
                        iteration,
                        len(answer),
                    )
                    return AgentRunResult(
                        final_message=answer,
                        iterations=iteration,
                    )
                elif iteration < self.settings.agent_max_iterations:
                    logger.warning(
                        "Iteration %s: empty model output; schema nudge",
                        iteration,
                    )
                    self._append(LLMMessage(role="user", content=SCHEMA_NUDGE))
                    continue
                else:
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

            logger.info(
                "Iteration %s: executing tools %s",
                iteration,
                [call.name for call in assistant.tool_calls],
            )
            final_message = self._tools._process_tool_calls(
                assistant.tool_calls, self._append
            )
            if final_message is not None:
                logger.info("Iteration %s: tool path returned final message", iteration)
                return AgentRunResult(
                    final_message=final_message,
                    iterations=iteration,
                )

            error_signature = _latest_tool_error_signature(self.messages)
            if error_signature:
                recent_tool_errors.append(error_signature)
                _notice(f"Tool error: {error_signature[:180]}")
                if (
                    len(recent_tool_errors) >= 3
                    and len(set(recent_tool_errors[-3:])) == 1
                ):
                    logger.error(
                        "Stopping after repeated tool error: %s",
                        error_signature,
                    )
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
