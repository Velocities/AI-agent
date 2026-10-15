"""CPU speech capture support for the API.

The phone records audio. This package transcribes it and synthesizes replies.
The agent turn itself stays on the existing conversation route.
"""

from ai_agent.speech.stt import SpeechToTextProvider, VoskSpeechToText
from ai_agent.speech.tts import KokoroTTS, TextToSpeechConverter

__all__ = [
    "KokoroTTS",
    "SpeechToTextProvider",
    "TextToSpeechConverter",
    "VoskSpeechToText",
]
