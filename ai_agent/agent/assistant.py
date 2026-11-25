from __future__ import annotations

import logging
from collections.abc import Callable

from ai_agent.agent.tools import CONTINUE_NUDGE
from ai_agent.config import Settings
from ai_agent.llm.base import LLMErrorKind, LLMMessage, LLMProvider, LLMResponse
from ai_agent.llm.streaming import (
    RespondMessageStreamer,
    ResumeOverlapTrimmer,
    trim_resume_overlap,
)

logger = logging.getLogger(__name__)

_RECOVERABLE_TRUNCATION_KINDS = frozenset(
    {
        LLMErrorKind.STREAM_INTERRUPTED,
        LLMErrorKind.STREAM_INCOMPLETE,
    }
)


class AssistantGenerator:
    """Ask the model for one assistant response, resuming if generation is cut off."""

    def __init__(
        self,
        llm: LLMProvider,
        settings: Settings,
        tool_definitions: list[dict],
    ) -> None:
        self.llm = llm
        self.settings = settings
        self.tool_definitions = tool_definitions

    def _generate_assistant_turn(
        self,
        messages: list[LLMMessage],
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
            prompt = self._resume_messages(messages, resume_tail) if produced else messages

            if streaming:
                response = self._chat_with_stream(
                    prompt,
                    stream_callback,
                    notice_callback,
                    resume_tail=resume_tail,
                )
            else:
                response = self.llm.chat(prompt, tools=self.tool_definitions)

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

    def _resume_messages(
        self, messages: list[LLMMessage], resume_tail: str
    ) -> list[LLMMessage]:
        """Prompt for resuming a cut-off answer.

        Only the tail of the partial answer is resent so the prompt stays a
        constant size; regrowing it each attempt is what exhausts the context
        window and makes the model restart from the beginning.
        """
        return [
            *messages,
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

        for chunk in self.llm.chat_stream(messages, tools=self.tool_definitions):
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

    @staticmethod
    def _was_cut_short(response: LLMResponse) -> bool:
        """True when generation stopped for a limit rather than being finished."""
        if response.stop_reason == "length":
            return AssistantGenerator._has_generation_output(response.message)
        if response.error_kind in _RECOVERABLE_TRUNCATION_KINDS:
            return AssistantGenerator._has_generation_output(response.message)
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
