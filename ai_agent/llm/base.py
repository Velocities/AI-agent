from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum


class LLMErrorKind(str, Enum):
    """Vendor-neutral failure classes for transport and generation."""

    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    HTTP = "http"
    PROTOCOL = "protocol"
    STREAM_INTERRUPTED = "stream_interrupted"
    STREAM_INCOMPLETE = "stream_incomplete"
    EMPTY = "empty"
    MODEL_NOT_FOUND = "model_not_found"


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


class LLMProvider(ABC):
    @property
    def endpoint(self) -> str:
        """Configured inference URL, if the provider has one."""
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
    def healthcheck(self) -> tuple[bool, str]:
        """Return whether the endpoint is usable, plus a short status message."""
        raise NotImplementedError

    def close(self) -> None:
        """Release session resources. Default is a no-op."""
        return None
