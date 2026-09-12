"""Backward-compatible re-exports. Prefer ai_agent.llm.client.types."""

from ai_agent.llm.client.types import (
    LLMHealthcheck,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    StreamChunk,
    ToolCall,
)
from ai_agent.llm.http.errors import LLMErrorKind

__all__ = [
    "LLMErrorKind",
    "LLMHealthcheck",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "StreamChunk",
    "ToolCall",
]
