"""Errors raised while preparing or processing speech audio."""


class SpeechError(Exception):
    """Base error for speech setup and audio handling."""


class SpeechNotConfigured(SpeechError):
    """A model path is empty or an optional speech package is missing."""


class SpeechAudioError(SpeechError):
    """The audio or the text cannot be processed."""
