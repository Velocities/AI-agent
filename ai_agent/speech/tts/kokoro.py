"""Text-to-speech converters.

`TextToSpeechConverter` is the swap point. The first implementation is
Kokoro-82M, which runs on CPU. A later engine would subclass this same class.
"""

from __future__ import annotations

import array
import logging
import sys
import threading
from pathlib import Path

from ai_agent.speech.abstract import TextToSpeechConverter
from ai_agent.speech.errors import SpeechAudioError, SpeechNotConfigured
from ai_agent.speech.text import text_for_speech
from ai_agent.speech.tts.kokoro_assets import KOKORO_MODEL_NAME, KOKORO_VOICES_NAME
from ai_agent.speech.wav import write_wav

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "af_heart"


def voices_path_for(model_path: Path, voices: str = "") -> Path:
    """Use an explicit voices file, or the one that sits beside the model."""
    chosen = voices.strip()
    if chosen:
        return Path(chosen)
    return Path(model_path).parent / KOKORO_VOICES_NAME


def lang_for_voice(voice: str) -> str:
    """Kokoro-82M phonemizer language for a voice id such as af_heart."""
    if voice.startswith(("bf_", "bm_")):
        return "en-gb"
    return "en-us"


def _pcm16_le(samples) -> bytes:
    """Pack float samples in [-1, 1] as little-endian 16-bit PCM."""
    clip = getattr(samples, "clip", None)
    astype = getattr(samples, "astype", None)
    if clip is not None and astype is not None:
        audio = astype("float32").reshape(-1).clip(-1.0, 1.0)
        return (audio * 32767.0).astype("<i2").tobytes()
    pcm = array.array("h")
    for sample in samples:
        value = float(sample)
        if value > 1.0:
            value = 1.0
        elif value < -1.0:
            value = -1.0
        pcm.append(int(value * 32767.0))
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()


def _load_voice(model_path: Path, voices_path: Path):
    """Open Kokoro-82M on CPU only."""
    if not model_path.is_file():
        raise SpeechNotConfigured(
            f"Kokoro-82M model not found: {model_path}. "
            f"Set SPEECH_TTS_MODEL to {KOKORO_MODEL_NAME}."
        )
    if not voices_path.is_file():
        raise SpeechNotConfigured(
            f"Kokoro voices not found: {voices_path}. "
            f"Set SPEECH_KOKORO_VOICES to {KOKORO_VOICES_NAME}."
        )
    try:
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
    except ImportError as exc:
        raise SpeechNotConfigured(
            "Kokoro is not installed. Install the voice extra: pip install -e '.[voice]'"
        ) from exc
    logger.info("Loading Kokoro-82M from %s on CPU", model_path)
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    # from_session reads this path when it checks that the weights exist.
    session._model_path = str(model_path)
    return Kokoro.from_session(session, str(voices_path))

class KokoroTTS(TextToSpeechConverter):
    """Synthesize speech with Kokoro-82M. One voice is shared across requests.

    The ONNX session is opened with CPUExecutionProvider only, so a CUDA build
    of ONNX Runtime installed for the language model is not used for speech.
    """

    def __init__(self, model_path: Path, voices_path: Path, voice: str = DEFAULT_VOICE):
        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self.voice = voice.strip() or DEFAULT_VOICE
        self._lock = threading.Lock()
        self._engine = None

    def synthesize(self, text: str) -> bytes:
        spoken = text_for_speech(text)
        if not spoken:
            raise SpeechAudioError("Nothing to speak.")
        engine = self._load()
        try:
            with self._lock:
                samples, sample_rate = engine.create(
                    spoken,
                    voice=self.voice,
                    speed=1.0,
                    lang=lang_for_voice(self.voice),
                )
        except ValueError as exc:
            message = str(exc)
            if "not found" in message.lower():
                raise SpeechNotConfigured(
                    f"Kokoro voice {self.voice!r} is not in {self.voices_path}. "
                    "Set SPEECH_KOKORO_VOICE to a voice id from that file."
                ) from exc
            raise SpeechAudioError(message) from exc
        if sample_rate <= 0 or len(samples) == 0:
            raise SpeechAudioError("Kokoro returned empty audio.")
        return write_wav(_pcm16_le(samples), sample_rate=int(sample_rate))

    def _load(self):
        with self._lock:
            if self._engine is None:
                self._engine = _load_voice(self.model_path, self.voices_path)
            return self._engine