from __future__ import annotations

import re


class RespondMessageStreamer:
    """Extract respond(message=...) text from streaming tool-call JSON.

    Text is only emitted once the partial JSON shows finished=true, because a
    finished=false message is an internal progress note rather than an answer.
    """

    _MESSAGE_KEY = re.compile(r'"message"\s*:\s*"')
    _FINISHED_TRUE = re.compile(r'"finished"\s*:\s*true\b')

    def __init__(self) -> None:
        self._arguments = ""
        self._streamed_length = 0

    def feed(self, delta: str) -> str:
        if not delta:
            return ""
        self._arguments += delta
        if not self._FINISHED_TRUE.search(self._arguments):
            return ""
        message = self._extract_message()
        new_text = message[self._streamed_length :]
        self._streamed_length = len(message)
        return new_text

    def flush_message(self, complete_message: str) -> str:
        """Emit any respond message text not yet streamed."""
        if not isinstance(complete_message, str):
            return ""
        remaining = complete_message[self._streamed_length :]
        self._streamed_length = len(complete_message)
        return remaining

    def _extract_message(self) -> str:
        match = self._MESSAGE_KEY.search(self._arguments)
        if not match:
            return ""
        return _decode_partial_json_string(self._arguments, match.end())


def _decode_partial_json_string(raw: str, start: int) -> str:
    """Decode a JSON string value that may still be incomplete."""
    chars: list[str] = []
    index = start
    pending_high: int | None = None

    while index < len(raw):
        char = raw[index]
        if char == '"':
            break
        if char != "\\":
            if pending_high is not None:
                chars.append("\ufffd")
                pending_high = None
            chars.append(char)
            index += 1
            continue

        if index + 1 >= len(raw):
            break

        escaped = raw[index + 1]
        if escaped == "u":
            if index + 5 >= len(raw):
                break
            hex_digits = raw[index + 2 : index + 6]
            if not all(digit in "0123456789abcdefABCDEF" for digit in hex_digits):
                break
            codepoint = int(hex_digits, 16)
            if 0xD800 <= codepoint <= 0xDBFF:
                if pending_high is not None:
                    chars.append("\ufffd")
                pending_high = codepoint
            elif 0xDC00 <= codepoint <= 0xDFFF:
                if pending_high is not None:
                    combined = (
                        0x10000
                        + ((pending_high - 0xD800) << 10)
                        + (codepoint - 0xDC00)
                    )
                    chars.append(chr(combined))
                    pending_high = None
                else:
                    chars.append("\ufffd")
            else:
                if pending_high is not None:
                    chars.append("\ufffd")
                    pending_high = None
                chars.append(chr(codepoint))
            index += 6
            continue

        if escaped not in {"n", "t", "r", '"', "\\", "/", "b", "f"}:
            break

        if pending_high is not None:
            chars.append("\ufffd")
            pending_high = None
        chars.append(_SIMPLE_ESCAPES[escaped])
        index += 2

    return "".join(chars)


_SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
}


def sanitize_terminal_text(text: str) -> str:
    """Remove lone surrogates that Windows terminals cannot encode."""
    if not text:
        return text
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return "".join(
            char if not 0xD800 <= ord(char) <= 0xDFFF else "\ufffd" for char in text
        )
