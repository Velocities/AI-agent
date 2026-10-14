"""Turn a model reply into a short string Piper can read."""

from __future__ import annotations

import re

_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN = re.compile(r"[#*_`>\[\]]+")

# A medium Piper voice on CPU is much slower than the chat stream.
MAX_SPOKEN_CHARS = 1500


def text_for_speech(text: str, *, limit: int = MAX_SPOKEN_CHARS) -> str:
    """Drop hidden reasoning and fenced code, then keep a spoken-length prefix."""
    cleaned = _THINK.sub(" ", text)
    cleaned = _FENCE.sub(" ", cleaned)
    cleaned = _MARKDOWN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    period = cut.rfind(". ")
    if period > limit // 2:
        return cut[: period + 1].strip()
    return cut.rstrip()
