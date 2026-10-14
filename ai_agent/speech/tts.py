"""Piper text-to-speech on the CPU.

Kokoro is a possible later replacement for this class if a more natural
voice is worth the extra runtime. This prototype does not load it and does
not add a second synthesis interface.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from pathlib import Path

from ai_agent.speech.errors import SpeechAudioError, SpeechNotConfigured
from ai_agent.speech.text import text_for_speech

logger = logging.getLogger(__name__)


def _load_voice(model_path: Path):
    """Open a Piper voice on CPU only.

    `use_cuda=False` keeps the ONNX session on CPUExecutionProvider even when
    a CUDA provider is installed for the language model.
    """
    if not model_path.is_file():
        raise SpeechNotConfigured(
            f"Piper voice not found: {model_path}. "
            "Set SPEECH_PIPER_MODEL to a Piper .onnx file."
        )
    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise SpeechNotConfigured(
            "Piper is not installed. Install the voice extra: pip install -e '.[voice]'"
        ) from exc
    logger.info("Loading Piper voice from %s on CPU", model_path)
    return PiperVoice.load(model_path, use_cuda=False)


class PiperTextToSpeech:
    """Synthesize speech with Piper. One voice is shared across requests."""

    def __init__(self, model_path: Path):
        self.model_path = Path(model_path)
        self._lock = threading.Lock()
        self._voice = None

    def synthesize(self, text: str) -> bytes:
        spoken = text_for_speech(text)
        if not spoken:
            raise SpeechAudioError("Nothing to speak.")
        voice = self._load()
        buffer = io.BytesIO()
        with self._lock:
            with wave.open(buffer, "wb") as wav:
                voice.synthesize_wav(spoken, wav)
        return buffer.getvalue()

    def _load(self):
        with self._lock:
            if self._voice is None:
                self._voice = _load_voice(self.model_path)
            return self._voice


def tts_from_settings(settings) -> PiperTextToSpeech:
    path = settings.speech_piper_model.strip()
    if not path:
        raise SpeechNotConfigured(
            "Speech synthesis is not set up. Set SPEECH_PIPER_MODEL to a Piper .onnx voice."
        )
    return PiperTextToSpeech(Path(path))
