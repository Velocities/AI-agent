"""Per-user personalization. Pronunciations are for speech, not the model prompt.

Speech choices (transcription engine, wake phrase, closing phrase, and whether
voice may approve commands) are stored here too. They never enter the model
prompt. Voice approval is an exact client-side gate, not a model judgment.
"""

from __future__ import annotations

import re
import unicodedata
import zoneinfo
from dataclasses import dataclass
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NAME_MAX = 40
PRONUNCIATION_MAX = 80
PHRASE_MAX = 80
CODING_PREFERENCES_MAX = 2000
TIMEZONE_MAX = 64
REPLY_LENGTHS = ("brief", "normal", "thorough")
# Ids shared with the Android client's SttProvider. google_remote is the default.
STT_PROVIDERS = ("google_remote", "google_local", "vosk")
DEFAULT_STT_PROVIDER = "google_remote"

_NAME = re.compile(r"^[\w][\w .'\-]*$", re.UNICODE)
_SPOKEN = re.compile(r"^[A-Za-z][A-Za-z .'\-]*$")
_PHRASE = re.compile(r"^[\w][\w .',\-]*$", re.UNICODE)


class PersonalizationError(ValueError):
    """A settings value cannot be stored."""


@dataclass(frozen=True)
class UserPreferences:
    """Stored preferences. Empty strings and reply length `normal` are the defaults."""

    strip_image_metadata: bool = True
    agent_name: str = ""
    agent_name_pronunciation: str = ""
    user_name: str = ""
    user_name_pronunciation: str = ""
    coding_preferences: str = ""
    reply_length: str = "normal"
    timezone: str = ""
    # Which phone-side transcriber the user picked. Not a model name on the server.
    stt_provider: str = DEFAULT_STT_PROVIDER
    # Empty means "Hey {agent name}" (or "Hey" when the agent is unnamed).
    wake_phrase: str = ""
    # Empty means "Bye {agent name}" (or "Bye" when the agent is unnamed).
    close_phrase: str = ""
    # Off until this user turns it on for this server. Voice yes/no stays refused.
    voice_command_approval: bool = False

    def speech_pairs(self) -> tuple[tuple[str, str], ...]:
        """Written name, then the respelling Kokoro should say. Longer names first."""
        pairs = []
        if self.agent_name and self.agent_name_pronunciation:
            pairs.append((self.agent_name, self.agent_name_pronunciation))
        if self.user_name and self.user_name_pronunciation:
            pairs.append((self.user_name, self.user_name_pronunciation))
        pairs.sort(key=lambda item: len(item[0]), reverse=True)
        return tuple(pairs)


def normalize_preferences(prefs: UserPreferences) -> UserPreferences:
    """Return a storable copy, or raise PersonalizationError."""
    agent_name, agent_spoken = _name_pair(
        prefs.agent_name,
        prefs.agent_name_pronunciation,
        "the agent name",
    )
    user_name, user_spoken = _name_pair(
        prefs.user_name,
        prefs.user_name_pronunciation,
        "your name",
    )
    coding = _coding_preferences(prefs.coding_preferences)
    reply_length = _reply_length(prefs.reply_length)
    timezone = _timezone(prefs.timezone)
    stt_provider = _stt_provider(prefs.stt_provider)
    wake_phrase = _phrase(prefs.wake_phrase, "The wake phrase")
    close_phrase = _phrase(prefs.close_phrase, "The closing phrase")
    if (
        wake_phrase
        and close_phrase
        and normalize_spoken(wake_phrase) == normalize_spoken(close_phrase)
    ):
        raise PersonalizationError("The wake phrase and the closing phrase need to be different.")
    return UserPreferences(
        strip_image_metadata=bool(prefs.strip_image_metadata),
        agent_name=agent_name,
        agent_name_pronunciation=agent_spoken,
        user_name=user_name,
        user_name_pronunciation=user_spoken,
        coding_preferences=coding,
        reply_length=reply_length,
        timezone=timezone,
        stt_provider=stt_provider,
        wake_phrase=wake_phrase,
        close_phrase=close_phrase,
        voice_command_approval=bool(prefs.voice_command_approval),
    )


def _name_pair(name: str, pronunciation: str, label: str) -> tuple[str, str]:
    written = _clean_line(name, NAME_MAX, label)
    spoken = _clean_line(pronunciation, PRONUNCIATION_MAX, f"the sounds-like field for {label}")
    if written and not _NAME.fullmatch(written):
        raise PersonalizationError(
            f"{label[:1].upper()}{label[1:]} can use letters, numbers, spaces, "
            "apostrophes, periods, and hyphens."
        )
    if spoken and not _SPOKEN.fullmatch(spoken):
        raise PersonalizationError(
            f"The sounds-like field for {label} must be plain English words, "
            "such as clue for CLU."
        )
    if not written:
        # Clearing the name clears its respelling, even if the client still sent one.
        return "", ""
    if not spoken:
        raise PersonalizationError(f"A sounds-like respelling is required for {label}.")
    return written, spoken


def _clean_line(value: str, limit: int, label: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if any(unicodedata.category(char).startswith("C") for char in text):
        raise PersonalizationError(f"{label[:1].upper()}{label[1:]} must be a single line.")
    if len(text) > limit:
        raise PersonalizationError(f"{label[:1].upper()}{label[1:]} must be at most {limit} characters.")
    return text


def _coding_preferences(value: str) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in text or any(unicodedata.category(char) == "Cc" and char != "\n" and char != "\t" for char in text):
        raise PersonalizationError("Coding preferences cannot include control characters.")
    if len(text) > CODING_PREFERENCES_MAX:
        raise PersonalizationError(
            f"Coding preferences must be at most {CODING_PREFERENCES_MAX} characters."
        )
    return text


def normalize_spoken(text: str) -> str:
    """Fold a phrase the way the Android gate compares it: case and punctuation aside.

    Letters and digits stay. Everything else becomes a space, then whitespace collapses.
    The client uses the same rule so "Hey, CLU!" matches a stored "Hey CLU".
    """
    chars = []
    for char in (text or "").lower():
        chars.append(char if char.isalnum() or char.isspace() else " ")
    return re.sub(r"\s+", " ", "".join(chars)).strip()


def _stt_provider(value: str) -> str:
    provider = (value or DEFAULT_STT_PROVIDER).strip().lower()
    if provider not in STT_PROVIDERS:
        raise PersonalizationError(
            "Transcription must be google_remote, google_local, or vosk."
        )
    return provider


def _phrase(value: str, label: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if any(unicodedata.category(char).startswith("C") for char in text):
        raise PersonalizationError(f"{label} must be a single line.")
    if len(text) > PHRASE_MAX:
        raise PersonalizationError(f"{label} must be at most {PHRASE_MAX} characters.")
    if not _PHRASE.fullmatch(text):
        raise PersonalizationError(
            f"{label} can use letters, numbers, spaces, apostrophes, periods, commas, and hyphens."
        )
    return text


def _reply_length(value: str) -> str:
    length = (value or "normal").strip().lower()
    if length not in REPLY_LENGTHS:
        raise PersonalizationError("Reply length must be brief, normal, or thorough.")
    return length


# Fixed-offset Etc/* names use an inverted sign (Etc/GMT+5 means UTC−5), so the
# picker offers city zones and UTC instead.
_PICKER_HIDDEN_PREFIXES = ("Etc/",)


@lru_cache(maxsize=1)
def selectable_timezones() -> tuple[str, ...]:
    """IANA zones the settings picker offers. Every entry is accepted by ZoneInfo."""
    names = [
        name
        for name in zoneinfo.available_timezones()
        if name == "UTC" or ("/" in name and not name.startswith(_PICKER_HIDDEN_PREFIXES))
    ]
    return tuple(sorted(names))


def _timezone(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) > TIMEZONE_MAX or any(char.isspace() for char in text):
        raise PersonalizationError("Timezone must be an IANA name such as America/New_York.")
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        raise PersonalizationError(
            "Timezone must be an IANA name such as America/New_York."
        ) from None
    return text
