"""WAV helpers for the 16 kHz mono clips the phone records.

Transcription accepts only that format. Synthesis writes whatever sample rate
Kokoro produces; the phone plays the header rather than assuming 16 kHz.
"""

from __future__ import annotations

import io
import wave

from ai_agent.speech.errors import SpeechAudioError

PCM_SAMPLE_RATE = 16_000


def pcm_from_wav(data: bytes) -> tuple[bytes, int]:
    """Return 16-bit little-endian mono PCM and its sample rate."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise SpeechAudioError(
            "Audio must be a mono 16-bit 16 kHz WAV file."
        ) from exc
    if channels != 1 or width != 2 or rate != PCM_SAMPLE_RATE:
        raise SpeechAudioError(
            "Audio must be a mono 16-bit 16 kHz WAV file."
        )
    if not frames:
        raise SpeechAudioError("Audio is empty.")
    return frames, rate


def write_wav(pcm: bytes, sample_rate: int = PCM_SAMPLE_RATE) -> bytes:
    """Wrap PCM in a WAV header. Used by tests and local fixtures."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()
