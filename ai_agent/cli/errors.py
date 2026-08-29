from __future__ import annotations

from ai_agent.llm.base import LLMErrorKind

# Startup: any failed healthcheck or warmup keeps the REPL from opening.
FATAL_STARTUP_KINDS = frozenset(
    {
        LLMErrorKind.UNAVAILABLE,
        LLMErrorKind.TIMEOUT,
        LLMErrorKind.HTTP,
        LLMErrorKind.PROTOCOL,
        LLMErrorKind.MODEL_NOT_FOUND,
        LLMErrorKind.EMPTY,
        LLMErrorKind.STREAM_INTERRUPTED,
        LLMErrorKind.STREAM_INCOMPLETE,
        LLMErrorKind.SESSION_CLOSED,
    }
)

# Mid-turn: stay in the REPL unless the session itself is gone.
FATAL_TURN_KINDS = frozenset({LLMErrorKind.SESSION_CLOSED})


def startup_should_exit(*, healthy: bool, warmup_ok: bool) -> bool:
    return not healthy or not warmup_ok


def is_fatal_startup_kind(error_kind: LLMErrorKind | None) -> bool:
    return error_kind in FATAL_STARTUP_KINDS


def turn_should_exit(error_kind: LLMErrorKind | None) -> bool:
    return error_kind in FATAL_TURN_KINDS
