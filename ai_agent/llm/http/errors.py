from __future__ import annotations

from enum import Enum


class LLMErrorKind(str, Enum):
    """Vendor-neutral failure classes for HTTP transport and generation."""

    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    HTTP = "http"
    PROTOCOL = "protocol"
    STREAM_INTERRUPTED = "stream_interrupted"
    STREAM_INCOMPLETE = "stream_incomplete"
    EMPTY = "empty"
    MODEL_NOT_FOUND = "model_not_found"
    SESSION_CLOSED = "session_closed"
