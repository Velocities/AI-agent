"""Speak a reply as its tokens arrive.

The caller supplies the text-to-speech converter already loaded for this
process. Sentence boundaries live here. The engine only sees one sentence
at a time and does not keep the conversation.
"""

from __future__ import annotations

import base64
import logging
import queue
import threading

from ai_agent.speech.errors import SpeechAudioError, SpeechNotConfigured
from ai_agent.speech.text import SpokenSentenceBuffer

logger = logging.getLogger(__name__)

SPEECH_NOT_CONFIGURED = (
    "Speech synthesis is not set up, so this reply will not be spoken."
)


class ReplySpeaker:
    """Feed spoken sentences to a `TextToSpeechConverter` on a side thread."""

    def __init__(self, speaker, emit, cancel: threading.Event) -> None:
        self._speaker = speaker
        self._emit = emit
        self._cancel = cancel
        self._buffer = SpokenSentenceBuffer()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._failed = False
        self._thread = threading.Thread(target=self._run, name="speech-stream", daemon=True)
        self._thread.start()

    def push(self, text: str) -> None:
        if self._failed or self._cancel.is_set():
            return
        for sentence in self._buffer.push(text):
            self._queue.put(sentence)

    def finish(self) -> None:
        """Speak the trailing fragment and wait until audio has been emitted."""
        if not self._failed and not self._cancel.is_set():
            for sentence in self._buffer.finish():
                self._queue.put(sentence)
        self._queue.put(None)
        self._thread.join()

    def _run(self) -> None:
        while True:
            sentence = self._queue.get()
            if sentence is None or self._cancel.is_set() or self._failed:
                break
            try:
                for wav in self._speaker.synthesize_stream(sentence):
                    if self._cancel.is_set():
                        break
                    if not wav:
                        continue
                    self._emit(
                        {
                            "type": "audio",
                            "wav_base64": base64.b64encode(wav).decode("ascii"),
                        }
                    )
            except SpeechAudioError:
                continue
            except SpeechNotConfigured as exc:
                self._fail(str(exc))
            except Exception:
                logger.exception("Speech synthesis failed")
                self._fail("Speech synthesis failed.")

    def _fail(self, message: str) -> None:
        if self._failed:
            return
        self._failed = True
        self._emit({"type": "audio", "error": message})
