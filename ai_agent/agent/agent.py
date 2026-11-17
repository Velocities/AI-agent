from __future__ import annotations

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
    ):
        self.settings = settings
        self.llm = llm
        self.policy = policy
        self.executor = executor
        self.router = router or ExecutionTargetRouter.local_only(executor)
        self.audit = audit
        self.prompter = prompter
        self.session = session
        self.tool_definitions = build_tool_definitions(self.router.names())
        runtime = runtime_context or gather_runtime_context(settings)
        system_prompt = append_personalization(
            build_system_prompt(
                runtime,
                policy.allowed_binaries(),
                self.router.summaries(),
                default_target=self.router.default_name,
                unlisted_need_approval=policy.unlisted_need_approval(),
            ),
            personalization,
        )
        self.messages: list[LLMMessage] = [
            LLMMessage(role="system", content=system_prompt)
        ]
        self.on_message: Callable[[LLMMessage], None] | None = None
        self.should_stop: Callable[[], bool] | None = None
        self._assistant = AssistantGenerator(llm, settings, self.tool_definitions)
        self._tools = ToolHandler(policy, prompter, self.router, audit, session)

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

    def run(
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

        for iteration in range(1, self.settings.agent_max_iterations + 1):
            self._raise_if_stopped()
            if iteration_callback is not None:
                iteration_callback(iteration)
            response = self._assistant._generate_assistant_turn(
                self.messages, stream_callback, notice_callback
            )

            assistant = response.message
            partial = (assistant.content or "").strip()

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
                if answer and looks_like_command_dump(answer):
                    if iteration < self.settings.agent_max_iterations:
                        self._append(
                            LLMMessage(role="user", content=COMMAND_DUMP_NUDGE)
                        )
                        continue
                if answer:
                    return AgentRunResult(
                        final_message=answer,
                        iterations=iteration,
                    )
                if iteration < self.settings.agent_max_iterations:
                    self._append(LLMMessage(role="user", content=SCHEMA_NUDGE))
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

            final_message = self._tools._process_tool_calls(
                assistant.tool_calls, self._append
            )
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
