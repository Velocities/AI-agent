"""Speech-to-text providers.

`SpeechToTextProvider` is the swap point. The first implementation is Vosk,
which runs on CPU. A later `faster-whisper` provider would subclass this
same class; it is not a dependency of this prototype.
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from ai_agent.speech.errors import SpeechAudioError, SpeechNotConfigured
from ai_agent.speech.wav import PCM_SAMPLE_RATE

logger = logging.getLogger(__name__)

_CHUNK_BYTES = 8000


class SpeechToTextProvider(ABC):
    """Transcribe 16-bit little-endian mono PCM into text."""

    @abstractmethod
    def transcribe(self, pcm: bytes, *, sample_rate: int) -> str:
        """Return the recognized text, or an empty string when nothing was said."""


class VoskSpeechToText(SpeechToTextProvider):
    """Vosk recognizer. The model is a directory from a Vosk model zip."""

    def __init__(self, model_path: Path):
        self.model_path = Path(model_path)
        self._lock = threading.Lock()
        self._model = None

    def transcribe(self, pcm: bytes, *, sample_rate: int) -> str:
        if sample_rate != PCM_SAMPLE_RATE:
            raise SpeechAudioError("Speech-to-text expects 16 kHz mono PCM.")
        if not pcm:
            raise SpeechAudioError("Audio is empty.")
        model = self._load_model()
        import vosk

        recognizer = vosk.KaldiRecognizer(model, sample_rate)
        view = memoryview(pcm)
        offset = 0
        while offset < len(view):
            recognizer.AcceptWaveform(bytes(view[offset : offset + _CHUNK_BYTES]))
            offset += _CHUNK_BYTES
        try:
            payload = json.loads(recognizer.FinalResult())
        except json.JSONDecodeError as exc:
            raise SpeechAudioError(
                "The speech recognizer returned an unreadable result."
            ) from exc
        text = payload.get("text", "") if isinstance(payload, dict) else ""
        if not isinstance(text, str):
            return ""
        return text.strip()

    def _load_model(self):
        with self._lock:
            if self._model is not None:
                return self._model
            if not self.model_path.is_dir():
                raise SpeechNotConfigured(
                    f"Vosk model directory not found: {self.model_path}. "
                    "Set SPEECH_STT_MODEL to an unpacked Vosk model."
                )
            try:
                import vosk
            except ImportError as exc:
                raise SpeechNotConfigured(
                    "Vosk is not installed. Install the voice extra: pip install -e '.[voice]'"
                ) from exc
            quiet = getattr(vosk, "SetLogLevel", None)
            if quiet is not None:
                quiet(-1)
            logger.info("Loading Vosk model from %s", self.model_path)
            self._model = vosk.Model(str(self.model_path))
            return self._model


def stt_from_settings(settings) -> SpeechToTextProvider:
    path = settings.speech_stt_model.strip()
    if not path:
        raise SpeechNotConfigured(
            "Speech-to-text is not set up. Set SPEECH_STT_MODEL to a Vosk model directory."
        )
    return VoskSpeechToText(Path(path))
