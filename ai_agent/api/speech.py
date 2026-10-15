"""HTTP endpoints for transcription and synthesis.

These routes do not run the agent. The client posts a transcript to the
existing turn stream, then posts the finished reply here to be spoken.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import require_deployment_access
from ai_agent.speech.errors import SpeechAudioError, SpeechNotConfigured
from ai_agent.speech.stt import SpeechToTextProvider, stt_from_settings
from ai_agent.speech.tts import TextToSpeechConverter, tts_from_settings
from ai_agent.speech.wav import pcm_from_wav

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/speech", tags=["speech"])

# A minute of 16 kHz mono 16-bit PCM is about 1.9 MB. 4 MB is a hard ceiling.
_MAX_AUDIO_BYTES = 4 * 1024 * 1024


class SpeechStatusResponse(BaseModel):
    stt_configured: bool
    tts_configured: bool
    stt_engine: str = "vosk"
    tts_engine: str = "kokoro"
    device: str = "cpu"


class SynthesizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=8000)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text is required")
        return value


class TranscriptResponse(BaseModel):
    text: str


def _stt_configured(request: Request) -> bool:
    if getattr(request.app.state, "speech_to_text", None) is not None:
        return True
    return bool(request.app.state.settings.speech_stt_model.strip())


def _tts_configured(request: Request) -> bool:
    if getattr(request.app.state, "text_to_speech", None) is not None:
        return True
    return bool(request.app.state.settings.speech_tts_model.strip())


def get_speech_to_text(request: Request) -> SpeechToTextProvider:
    current = getattr(request.app.state, "speech_to_text", None)
    if current is not None:
        return current
    try:
        provider = stt_from_settings(request.app.state.settings)
    except SpeechNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    request.app.state.speech_to_text = provider
    return provider


def get_text_to_speech(request: Request) -> TextToSpeechConverter:
    current = getattr(request.app.state, "text_to_speech", None)
    if current is not None:
        return current
    try:
        speaker = tts_from_settings(request.app.state.settings)
    except SpeechNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    request.app.state.text_to_speech = speaker
    return speaker


@router.get("/status", response_model=SpeechStatusResponse)
def speech_status(
    request: Request,
    _user: AuthenticatedUser = Depends(require_deployment_access),
) -> SpeechStatusResponse:
    return SpeechStatusResponse(
        stt_configured=_stt_configured(request),
        tts_configured=_tts_configured(request),
    )


@router.post("/transcribe", response_model=TranscriptResponse)
def transcribe_audio(
    request: Request,
    audio: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_deployment_access),
) -> TranscriptResponse:
    raw = audio.file.read(_MAX_AUDIO_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="Audio is empty.")
    if len(raw) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording is too long.")
    provider = get_speech_to_text(request)
    logger.info("Transcribing %s bytes for %s", len(raw), user.user_id)
    try:
        pcm, sample_rate = pcm_from_wav(raw)
        text = provider.transcribe(pcm, sample_rate=sample_rate)
    except SpeechAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except SpeechNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except Exception:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail="Transcription failed.") from None
    return TranscriptResponse(text=text)


@router.post("/synthesize")
def synthesize_speech(
    body: SynthesizeRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_deployment_access),
) -> Response:
    speaker = get_text_to_speech(request)
    logger.info("Synthesizing %s characters for %s", len(body.text), user.user_id)
    try:
        wav = speaker.synthesize(body.text)
    except SpeechAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except SpeechNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except Exception:
        logger.exception("Speech synthesis failed")
        raise HTTPException(status_code=500, detail="Speech synthesis failed.") from None
    return Response(content=wav, media_type="audio/wav")
