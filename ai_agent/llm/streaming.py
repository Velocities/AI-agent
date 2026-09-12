"""Backward-compatible re-exports. Prefer ai_agent.llm.client.streaming."""

from ai_agent.llm.client.streaming import (
    RespondMessageStreamer,
    ResumeOverlapTrimmer,
    sanitize_terminal_text,
    trim_resume_overlap,
)

__all__ = [
    "RespondMessageStreamer",
    "ResumeOverlapTrimmer",
    "sanitize_terminal_text",
    "trim_resume_overlap",
]
