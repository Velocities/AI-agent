"""Turn a model reply into a short string a speech engine can read."""

from __future__ import annotations

import re

_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN = re.compile(r"[#*_`>\[\]]+")
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
_FENCE_MARK = "```"

# Kokoro-82M on CPU is much slower than the chat stream.
MAX_SPOKEN_CHARS = 1500
# A tiny sentence joins the next one so "Yes." is not its own clip.
_MIN_SENTENCE_CHARS = 12
# A run with no punctuation is still handed to the engine before it gets huge.
_MAX_SENTENCE_CHARS = 400
_ABBREVIATIONS = frozenset(
    {
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "eg",
        "ie",
    }
)
_DOTTED = frozenset({"e.g.", "i.e.", "u.s.", "a.m.", "p.m."})


def clean_spoken(text: str) -> str:
    """Drop hidden reasoning, fenced code, and markdown."""
    cleaned = _THINK.sub(" ", text)
    cleaned = _FENCE.sub(" ", cleaned)
    cleaned = _MARKDOWN.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def text_for_speech(text: str, *, limit: int = MAX_SPOKEN_CHARS) -> str:
    """Drop hidden reasoning and fenced code, then keep a spoken-length prefix."""
    cleaned = clean_spoken(text)
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    period = cut.rfind(". ")
    if period > limit // 2:
        return cut[: period + 1].strip()
    return cut.rstrip()


class SpokenSentenceBuffer:
    """Pull finished sentences out of a token stream.

    Sentence ends are `.`, `?`, `!`, and newlines. Commas stay inside the
    sentence. Abbreviations and decimals are not splits. Short sentences join
    the next one. `<think>` blocks and fenced code are left unspoken.
    """

    def __init__(self, limit: int = MAX_SPOKEN_CHARS) -> None:
        self._limit = limit
        self._spoken = 0
        self._held = ""
        self._pending = ""
        self._carry = ""
        self._mode = "text"

    def push(self, text: str) -> list[str]:
        """Append tokens and return sentences that are ready to speak."""
        if not text or self._spoken >= self._limit:
            return []
        self._carry += text
        self._pull_raw(final=False)
        return self._pull_sentences(final=False)

    def finish(self) -> list[str]:
        """Speak whatever visible text is still waiting."""
        if self._spoken >= self._limit and not self._held:
            self._carry = ""
            self._pending = ""
            return []
        self._pull_raw(final=True)
        ready = self._pull_sentences(final=True)
        held = self._held
        self._held = ""
        if held:
            ready.append(held)
        return ready

    def _pull_raw(self, *, final: bool) -> None:
        while self._carry:
            if self._mode == "think":
                close = self._carry.lower().find(_THINK_CLOSE)
                if close < 0:
                    if final:
                        self._carry = ""
                    return
                self._carry = self._carry[close + len(_THINK_CLOSE) :]
                self._mode = "text"
                continue
            if self._mode == "fence":
                close = self._carry.find(_FENCE_MARK)
                if close < 0:
                    if final:
                        self._carry = ""
                    return
                self._carry = self._carry[close + len(_FENCE_MARK) :]
                self._mode = "text"
                continue
            think = self._carry.lower().find(_THINK_OPEN)
            fence = self._carry.find(_FENCE_MARK)
            partial = -1 if final else _partial_opener_index(self._carry)
            cut = len(self._carry)
            opener = ""
            if think >= 0:
                cut = think
                opener = _THINK_OPEN
            if fence >= 0 and fence < cut:
                cut = fence
                opener = _FENCE_MARK
            if partial >= 0 and partial < cut:
                cut = partial
                opener = ""
            self._pending += self._carry[:cut]
            self._carry = self._carry[cut:]
            if opener == _THINK_OPEN:
                self._carry = self._carry[len(_THINK_OPEN) :]
                self._mode = "think"
                continue
            if opener == _FENCE_MARK:
                self._carry = self._carry[len(_FENCE_MARK) :]
                self._mode = "fence"
                continue
            return

    def _pull_sentences(self, *, final: bool) -> list[str]:
        pieces, rest = _split_ready(self._pending, final=final)
        self._pending = rest
        ready: list[str] = []
        for piece in pieces:
            ready.extend(self._accept(piece))
            if self._spoken >= self._limit:
                self._pending = ""
                self._carry = ""
                break
        return ready

    def _accept(self, raw: str) -> list[str]:
        if self._spoken >= self._limit:
            return []
        cleaned = clean_spoken(raw)
        if not cleaned:
            return []
        room = self._limit - self._spoken
        if len(cleaned) > room:
            clipped = cleaned[:room]
            space = clipped.rfind(" ")
            if space > 0:
                clipped = clipped[:space]
            cleaned = clipped.rstrip()
            if not cleaned:
                self._spoken = self._limit
                return []
            self._spoken = self._limit
            if self._held:
                cleaned = f"{self._held} {cleaned}".strip()
                self._held = ""
            return [cleaned]
        self._spoken += len(cleaned)
        if self._held:
            cleaned = f"{self._held} {cleaned}".strip()
            self._held = ""
        if len(cleaned) < _MIN_SENTENCE_CHARS and self._spoken < self._limit:
            self._held = cleaned
            return []
        return [cleaned]


def _split_ready(visible: str, *, final: bool) -> tuple[list[str], str]:
    pieces: list[str] = []
    start = 0
    index = 0
    while index < len(visible):
        if _is_boundary(visible, start, index, final=final):
            pieces.append(visible[start : index + 1])
            start = index + 1
            while start < len(visible) and visible[start] in " \t":
                start += 1
            index = start
            continue
        if not final and index - start >= _MAX_SENTENCE_CHARS:
            space = visible.rfind(" ", start, start + _MAX_SENTENCE_CHARS)
            split = space if space > start else start + _MAX_SENTENCE_CHARS
            pieces.append(visible[start:split])
            start = split
            while start < len(visible) and visible[start] == " ":
                start += 1
            index = start
            continue
        index += 1
    if final and start < len(visible):
        pieces.append(visible[start:])
        start = len(visible)
    return pieces, visible[start:]


def _is_boundary(text: str, start: int, index: int, *, final: bool) -> bool:
    char = text[index]
    if char == "\n":
        return True
    if char not in ".!?":
        return False
    if char == "." and _abbreviation(text, start, index):
        return False
    if char == "." and index > 0 and text[index - 1].isdigit():
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if nxt.isdigit() or (not nxt and not final):
            return False
    if index + 1 >= len(text):
        return final
    return text[index + 1].isspace()


def _abbreviation(text: str, start: int, dot: int) -> bool:
    word_start = dot
    while word_start > start and text[word_start - 1].isalpha():
        word_start -= 1
    if text[word_start:dot].lower() in _ABBREVIATIONS:
        return True
    window = text[max(start, dot - 3) : dot + 1].lower().replace(" ", "")
    return window in _DOTTED


def _partial_opener_index(text: str) -> int:
    """Index of a `<think>` or fence prefix that is still arriving, or -1."""
    lowered = text.lower()
    best = -1
    for marker in (_THINK_OPEN, _FENCE_MARK):
        haystack = lowered if marker.startswith("<") else text
        prefix = marker.lower() if marker.startswith("<") else marker
        for length in range(len(prefix) - 1, 0, -1):
            if haystack.endswith(prefix[:length]):
                index = len(text) - length
                if best < 0 or index < best:
                    best = index
                break
    return best
