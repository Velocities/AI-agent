from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum

from ai_agent.llm.http.errors import LLMErrorKind


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMMessage:
    role: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LLMResponse:
    message: LLMMessage
    done: bool = True
    model: str | None = None
    error: str | None = None
    error_kind: LLMErrorKind | None = None
    stop_reason: str | None = None


@dataclass
class StreamChunk:
    """Incremental data from a streaming LLM response."""

    content_delta: str | None = None
    tool_name: str | None = None
    tool_arguments_delta: str | None = None
    done: bool = False
    response: LLMResponse | None = None
    error: str | None = None
    error_kind: LLMErrorKind | None = None


@dataclass(frozen=True)
class LLMHealthcheck:
    ok: bool
    message: str
    error_kind: LLMErrorKind | None = None


@dataclass(frozen=True)
class LlmServerInfo:
    """Metadata from the agent LLM server's canonical /api/info endpoint."""

    engine: str
    model: str
    upstream: str = ""


class LLMProvider(ABC):
    @property
    def endpoint(self) -> str:
        """Configured inference URL."""
        return ""

    @property
    def engine_name(self) -> str:
        """Human-readable engine name reported by the server, if known."""
        return ""

    @property
    def model_name(self) -> str:
        """Model name configured for this session."""
        return ""

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> Iterator[StreamChunk]:
        """Stream a chat completion. Default implementation wraps batch chat."""
        response = self.chat(messages, tools)
        yield StreamChunk(
            done=True,
            response=response,
            error=response.error,
            error_kind=response.error_kind,
        )

    @abstractmethod
    def healthcheck(self) -> LLMHealthcheck:
        """Return whether the endpoint is usable, plus a short status message."""
        raise NotImplementedError

    def server_info(self) -> LlmServerInfo | None:
        """Return server metadata when the facade exposes /api/info."""
        return None

    def close(self) -> None:
        """Release session resources. Default is a no-op."""
        return None
