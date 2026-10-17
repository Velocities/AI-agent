"""Speech engine interfaces and the settings factories that build them.

`SpeechToTextConverter` is the swap point. The first implementation is Vosk,
which runs on CPU. A later `faster-whisper` provider would subclass this
same class; it is not a dependency of this prototype.

`TextToSpeechConverter` is the swap point. The first implementation is
Kokoro-82M, which runs on CPU. A later engine would subclass this same class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ai_agent.speech.errors import SpeechNotConfigured

DEFAULT_VOICE = "af_heart"
VOICES_FILENAME = "voices-v1.0.bin"



# Front-facing interface for speech-to-text conversion
class SpeechToTextConverter(ABC):
    """Transcribe 16-bit little-endian mono PCM into text."""

    @abstractmethod
    def transcribe(self, pcm: bytes, *, sample_rate: int) -> str:
        """Return the recognized text, or an empty string when nothing was said."""


def stt_from_settings(settings) -> SpeechToTextConverter:
    from ai_agent.speech.stt.vosk import VoskSpeechToText

    path = settings.speech_stt_model.strip()
    if not path:
        raise SpeechNotConfigured(
            "Speech-to-text is not set up. Set SPEECH_STT_MODEL to a Vosk model directory."
        )
    return VoskSpeechToText(Path(path))


def voices_path_for(model_path: Path, voices: str = "") -> Path:
    """Use an explicit voices file, or the one that sits beside the model."""
    chosen = voices.strip()
    if chosen:
        return Path(chosen)
    return Path(model_path).parent / VOICES_FILENAME


# Front-facing interface for text-to-speech conversion
class TextToSpeechConverter(ABC):
    """Turn reply text into a mono 16-bit WAV file."""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Return WAV bytes. The header carries this engine's sample rate."""


def tts_from_settings(settings) -> TextToSpeechConverter:
    from ai_agent.speech.tts.kokoro import KokoroTTS

    path = settings.speech_tts_model.strip()
    if not path:
        raise SpeechNotConfigured(
            "Speech synthesis is not set up. "
            "Set SPEECH_TTS_MODEL to the Kokoro-82M kokoro-v1.0.onnx file."
        )
    model_path = Path(path)
    voices = settings.speech_kokoro_voices
    voice = settings.speech_kokoro_voice or DEFAULT_VOICE
    return KokoroTTS(
        model_path,
        voices_path_for(model_path, voices),
        voice,
    )
