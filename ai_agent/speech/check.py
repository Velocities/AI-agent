"""Startup checks for speech paths.

A bad path is logged and ignored. Chat and the rest of the API keep running.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ai_agent.speech.tts import voices_path_for

logger = logging.getLogger(__name__)


def speech_configuration_problems(settings) -> list[str]:
    """Return problems with configured speech paths. Empty paths are off, not errors."""
    problems: list[str] = []
    try:
        stt = settings.speech_stt_model.strip()
        if stt and not Path(stt).is_dir():
            problems.append(f"SPEECH_STT_MODEL is not a Vosk model directory: {stt}.")
        tts = settings.speech_tts_model.strip()
        if tts:
            model = Path(tts)
            if not model.is_file():
                problems.append(f"SPEECH_TTS_MODEL is not a Kokoro-82M model file: {tts}.")
            else:
                voices = voices_path_for(model, settings.speech_kokoro_voices)
                if not voices.is_file():
                    problems.append(
                        f"Kokoro voices file not found: {voices}. "
                        "Set SPEECH_KOKORO_VOICES or place voices-v1.0.bin beside the model."
                    )
    except Exception as exc:
        problems.append(f"Speech settings could not be read: {exc}.")
    return problems


def note_speech_configuration(settings) -> None:
    """Log configuration problems. Never raises."""
    try:
        problems = speech_configuration_problems(settings)
    except Exception:
        logger.exception(
            "Speech configuration check failed. The rest of the API will keep running."
        )
        return
    for problem in problems:
        logger.error("%s Speech stays off. The rest of the API will keep running.", problem)
