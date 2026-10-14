"""Speech HTTP routes. Engines are stand-ins so the tests need no model files."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
from ai_agent.api.speech import _MAX_AUDIO_BYTES
from ai_agent.config import Settings
from ai_agent.speech.stt import SpeechToTextProvider
from ai_agent.speech.wav import write_wav

_USER = "11111111-1111-4111-8111-111111111111"


class _Tokens:
    def verify(self, token: str) -> AuthenticatedUser:
        if token != "good":
            raise InvalidTokenError("no")
        return AuthenticatedUser(user_id=_USER)


class _FakeStt(SpeechToTextProvider):
    def __init__(self) -> None:
        self.sample_rate = 0
        self.pcm = b""

    def transcribe(self, pcm: bytes, *, sample_rate: int) -> str:
        self.pcm = pcm
        self.sample_rate = sample_rate
        return "turn the lights off"


class _FakeTts:
    def __init__(self) -> None:
        self.text = ""

    def synthesize(self, text: str) -> bytes:
        self.text = text
        return write_wav(b"\x01\x00" * 20, sample_rate=22050)


def _client() -> TestClient:
    app = create_app(
        Settings(
            supabase_url="",
            supabase_anon_key="",
            supabase_jwt_secret="",
            speech_stt_model="",
            speech_piper_model="",
        ),
        _Tokens(),
    )
    return TestClient(app)


def test_speech_requires_a_token_and_models() -> None:
    pcm = b"\x00\x00" * 160
    wav = write_wav(pcm)
    with _client() as client:
        missing = client.get("/api/speech/status")
        status = client.get("/api/speech/status", headers={"Authorization": "Bearer good"})
        rejected = client.post(
            "/api/speech/transcribe",
            headers={"Authorization": "Bearer good"},
            files={"audio": ("prompt.wav", wav, "audio/wav")},
        )
        silent = client.post(
            "/api/speech/synthesize",
            headers={"Authorization": "Bearer good"},
            json={"text": "Hello"},
        )
    assert missing.status_code == 401
    assert status.status_code == 200
    assert status.json()["stt_configured"] is False
    assert status.json()["tts_configured"] is False
    assert status.json()["device"] == "cpu"
    assert status.json()["stt_engine"] == "vosk"
    assert status.json()["tts_engine"] == "piper"
    assert rejected.status_code == 503
    assert silent.status_code == 503


def test_transcribe_and_synthesize_use_the_injected_engines() -> None:
    stt = _FakeStt()
    tts = _FakeTts()
    pcm = b"\x10\x00" * 200
    with _client() as client:
        client.app.state.speech_to_text = stt
        client.app.state.text_to_speech = tts
        status = client.get("/api/speech/status", headers={"Authorization": "Bearer good"})
        heard = client.post(
            "/api/speech/transcribe",
            headers={"Authorization": "Bearer good"},
            files={"audio": ("prompt.wav", write_wav(pcm), "audio/wav")},
        )
        spoken = client.post(
            "/api/speech/synthesize",
            headers={"Authorization": "Bearer good"},
            json={"text": "Hello there"},
        )
        blank = client.post(
            "/api/speech/synthesize",
            headers={"Authorization": "Bearer good"},
            json={"text": "   "},
        )
        garbage = client.post(
            "/api/speech/transcribe",
            headers={"Authorization": "Bearer good"},
            files={"audio": ("prompt.wav", b"not wav", "audio/wav")},
        )
        too_long = client.post(
            "/api/speech/transcribe",
            headers={"Authorization": "Bearer good"},
            files={"audio": ("prompt.wav", b"R" * (_MAX_AUDIO_BYTES + 1), "audio/wav")},
        )
    assert status.json()["stt_configured"] is True
    assert status.json()["tts_configured"] is True
    assert heard.status_code == 200
    assert heard.json() == {"text": "turn the lights off"}
    assert stt.sample_rate == 16_000
    assert stt.pcm == pcm
    assert spoken.status_code == 200
    assert spoken.headers["content-type"].startswith("audio/wav")
    assert spoken.content[:4] == b"RIFF"
    assert tts.text == "Hello there"
    assert blank.status_code == 422
    assert garbage.status_code == 400
    assert too_long.status_code == 413
