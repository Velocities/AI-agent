"""Speech engine interfaces and the settings factories that build them.

`SpeechToTextConverter` is the swap point. The first implementation is Vosk,
which runs on CPU. A later `faster-whisper` provider would subclass this
same class; it is not a dependency of this prototype.

`TextToSpeechConverter` is the swap point. The first implementation is
Kokoro-82M, which runs on CPU. A later engine would subclass this same class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from ai_agent.speech.errors import SpeechNotConfigured


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


# Front-facing interface for text-to-speech conversion
class TextToSpeechConverter(ABC):
    """Turn reply text into mono 16-bit WAV audio.

    `synthesize` returns one clip. `synthesize_stream` yields clips as the
    engine produces them. The default stream is that one clip, so an engine
    that cannot start early still satisfies the interface.
    """

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Return WAV bytes. The header carries this engine's sample rate."""

    def synthesize_stream(self, text: str) -> Iterator[bytes]:
        """Yield WAV clips. Each clip can be played on its own."""
        yield self.synthesize(text)


def tts_from_settings(settings) -> TextToSpeechConverter:
    from ai_agent.speech.tts.kokoro import DEFAULT_VOICE, KokoroTTS, voices_path_for

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
