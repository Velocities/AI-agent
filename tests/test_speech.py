"""Speech helpers, the Vosk provider, and CPU-only Piper loading."""

from __future__ import annotations

import io
import json
import os
import sys
import wave
from pathlib import Path
from types import ModuleType

import pytest

from ai_agent.speech.errors import SpeechAudioError, SpeechNotConfigured
from ai_agent.speech.stt import SpeechToTextProvider, VoskSpeechToText, stt_from_settings
from ai_agent.speech.text import text_for_speech
from ai_agent.speech.tts import PiperTextToSpeech, tts_from_settings
from ai_agent.speech.wav import pcm_from_wav, write_wav


class _Settings:
    def __init__(self, stt: str = "", piper: str = ""):
        self.speech_stt_model = stt
        self.speech_piper_model = piper


def test_provider_cannot_be_constructed() -> None:
    with pytest.raises(TypeError):
        SpeechToTextProvider()  # type: ignore[abstract]
    assert SpeechToTextProvider.transcribe.__isabstractmethod__ is True


def test_wav_round_trip_and_rejected_shapes() -> None:
    pcm = b"\x01\x00\x02\x00" * 40
    encoded = write_wav(pcm)
    decoded, rate = pcm_from_wav(encoded)
    assert decoded == pcm
    assert rate == 16_000
    with pytest.raises(SpeechAudioError):
        pcm_from_wav(b"not-a-wav")
    with pytest.raises(SpeechAudioError):
        pcm_from_wav(write_wav(pcm, sample_rate=8000))
    stereo = io.BytesIO()
    with wave.open(stereo, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 8)
    with pytest.raises(SpeechAudioError):
        pcm_from_wav(stereo.getvalue())


def test_text_for_speech_drops_reasoning_and_code() -> None:
    spoken = text_for_speech("Hello <think>secret plan</think> world.\n```print(1)``` Thanks.")
    assert spoken == "Hello world. Thanks."
    assert "secret" not in spoken
    assert text_for_speech("   ") == ""
    long = "word " * 2000
    assert len(text_for_speech(long)) <= 1500


def test_settings_require_model_paths() -> None:
    with pytest.raises(SpeechNotConfigured):
        stt_from_settings(_Settings())
    with pytest.raises(SpeechNotConfigured):
        tts_from_settings(_Settings())


def test_vosk_rejects_bad_audio_before_loading(tmp_path: Path) -> None:
    provider = VoskSpeechToText(tmp_path / "missing")
    with pytest.raises(SpeechAudioError):
        provider.transcribe(b"\x00\x00", sample_rate=8000)
    with pytest.raises(SpeechNotConfigured):
        provider.transcribe(b"\x00\x00", sample_rate=16_000)


def test_vosk_transcribes_with_a_stand_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    seen: dict[str, object] = {}

    class _Model:
        def __init__(self, path: str):
            seen["path"] = path

    class _Recognizer:
        def __init__(self, model: object, sample_rate: int):
            seen["rate"] = sample_rate
            self._chunks: list[bytes] = []

        def AcceptWaveform(self, data: bytes) -> bool:
            self._chunks.append(data)
            return False

        def FinalResult(self) -> str:
            seen["bytes"] = sum(len(chunk) for chunk in self._chunks)
            return json.dumps({"text": "turn on the lights"})

    vosk = ModuleType("vosk")
    vosk.Model = _Model  # type: ignore[attr-defined]
    vosk.KaldiRecognizer = _Recognizer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    text = VoskSpeechToText(model_dir).transcribe(b"\x00\x01" * 100, sample_rate=16_000)
    assert text == "turn on the lights"
    assert seen["rate"] == 16_000
    assert seen["bytes"] == 200
    assert seen["path"] == str(model_dir)


def test_piper_loads_on_cpu_and_speaks_cleaned_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "en.onnx"
    model.write_bytes(b"not-a-real-model")
    seen: dict[str, object] = {}

    class _Voice:
        @staticmethod
        def load(path: Path, use_cuda: bool = True):
            seen["path"] = path
            seen["use_cuda"] = use_cuda
            return _Voice()

        def synthesize_wav(self, text: str, wav_file: wave.Wave_write) -> None:
            seen["text"] = text
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x00" * 8)

    piper = ModuleType("piper")
    piper.PiperVoice = _Voice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", piper)
    wav = PiperTextToSpeech(model).synthesize("Hello <think>hidden</think> world")
    assert seen["use_cuda"] is False
    assert seen["path"] == model
    assert seen["text"] == "Hello world"
    assert wav[:4] == b"RIFF"
    with pytest.raises(SpeechAudioError):
        PiperTextToSpeech(model).synthesize("<think>only a thought</think>")


def test_piper_missing_voice_file(tmp_path: Path) -> None:
    with pytest.raises(SpeechNotConfigured):
        PiperTextToSpeech(tmp_path / "missing.onnx").synthesize("Hello")


def test_voice_extra_does_not_pull_future_engines() -> None:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    voice = text.split("voice = [", 1)[1].split("]", 1)[0].lower()
    assert "piper-tts" in voice
    assert "vosk" in voice
    assert "faster-whisper" not in voice
    assert "kokoro" not in voice


@pytest.mark.voice_live
def test_vosk_live_silence() -> None:
    model = os.environ.get("SPEECH_STT_MODEL", "").strip()
    if not model:
        pytest.skip("Set SPEECH_STT_MODEL to an unpacked Vosk model")
    pytest.importorskip("vosk")
    text = VoskSpeechToText(Path(model)).transcribe(b"\x00\x00" * 16_000, sample_rate=16_000)
    assert isinstance(text, str)


@pytest.mark.voice_live
def test_piper_live_cpu_smoke() -> None:
    model = os.environ.get("SPEECH_PIPER_MODEL", "").strip()
    if not model:
        pytest.skip("Set SPEECH_PIPER_MODEL to a Piper .onnx voice")
    pytest.importorskip("piper")
    wav = PiperTextToSpeech(Path(model)).synthesize("Hello from the voice prototype.")
    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() > 0
        assert handle.getnframes() > 0
