"""Speech helpers, the Vosk provider, and CPU-only Kokoro-82M loading."""

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
from ai_agent.speech.stt import SpeechToTextConverter, VoskSpeechToText, stt_from_settings
from ai_agent.speech.text import SpokenSentenceBuffer, text_for_speech
from ai_agent.speech.tts import KokoroTTS, TextToSpeechConverter, lang_for_voice, tts_from_settings
from ai_agent.speech.wav import pcm_from_wav, write_wav


class _Settings:
    def __init__(self, stt: str = "", kokoro: str = "", voices: str = "", voice: str = ""):
        self.speech_stt_model = stt
        self.speech_tts_model = kokoro
        self.speech_kokoro_voices = voices
        self.speech_kokoro_voice = voice


def test_provider_cannot_be_constructed() -> None:
    with pytest.raises(TypeError):
        SpeechToTextConverter()  # type: ignore[abstract]
    assert SpeechToTextConverter.transcribe.__isabstractmethod__ is True
    with pytest.raises(TypeError):
        TextToSpeechConverter()  # type: ignore[abstract]
    assert TextToSpeechConverter.synthesize.__isabstractmethod__ is True
    assert issubclass(KokoroTTS, TextToSpeechConverter)


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


def test_sentence_buffer_speaks_finished_sentences_and_skips_hidden_text() -> None:
    buffer = SpokenSentenceBuffer()
    ready = buffer.push("The lights are already off. ")
    assert ready == ["The lights are already off."]
    assert buffer.push("Dr. Smith set it to 3.14 degrees. ") == [
        "Dr. Smith set it to 3.14 degrees."
    ]
    hidden = SpokenSentenceBuffer()
    assert hidden.push("Hello <think>secret</think> world. ") == ["Hello world."]
    fenced = SpokenSentenceBuffer()
    assert fenced.push("Look.\n```\nprint(1)\n```\nThanks for waiting. ") == [
        "Look. Thanks for waiting."
    ]
    pieces: list[str] = []
    streamed = SpokenSentenceBuffer()
    whole = "Yes. The lights are already off. "
    for index in range(len(whole)):
        pieces.extend(streamed.push(whole[index]))
    pieces.extend(streamed.finish())
    assert pieces == ["Yes. The lights are already off."]


def test_sentence_buffer_flushes_a_short_reply_and_stops_at_the_cap() -> None:
    buffer = SpokenSentenceBuffer()
    assert buffer.push("Hello") == []
    assert buffer.finish() == ["Hello"]
    capped = SpokenSentenceBuffer(limit=12)
    assert capped.push("The lights are already off. More words follow. ") == ["The lights"]
    assert capped.finish() == []


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


def test_kokoro_loads_on_cpu_and_speaks_cleaned_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"not-a-real-model")
    voices.write_bytes(b"not-real-voices")
    seen: dict[str, object] = {}

    class _Session:
        def __init__(self, path: str, providers: list[str] | None = None):
            seen["path"] = path
            seen["providers"] = providers

    class _Engine:
        @classmethod
        def from_session(cls, session: object, voices_path: str):
            seen["session"] = session
            seen["voices"] = voices_path
            seen["model_path"] = session._model_path
            return cls()

        def create(self, text: str, voice: str, speed: float, lang: str):
            seen["text"] = text
            seen["voice"] = voice
            seen["speed"] = speed
            seen["lang"] = lang
            return [0.0, 0.5, -0.5], 24000

    kokoro_onnx = ModuleType("kokoro_onnx")
    kokoro_onnx.Kokoro = _Engine  # type: ignore[attr-defined]
    onnxruntime = ModuleType("onnxruntime")
    onnxruntime.InferenceSession = _Session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kokoro_onnx", kokoro_onnx)
    monkeypatch.setitem(sys.modules, "onnxruntime", onnxruntime)
    wav = KokoroTTS(model, voices, voice="bf_emma").synthesize(
        "Hello <think>hidden</think> world"
    )
    assert seen["providers"] == ["CPUExecutionProvider"]
    assert seen["path"] == str(model)
    assert seen["voices"] == str(voices)
    assert seen["model_path"] == str(model)
    assert seen["text"] == "Hello world"
    assert seen["voice"] == "bf_emma"
    assert seen["lang"] == "en-gb"
    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 24000
        assert handle.getnframes() == 3
    with pytest.raises(SpeechAudioError):
        KokoroTTS(model, voices).synthesize("<think>only a thought</think>")


def test_kokoro_stream_yields_each_library_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    seen: dict[str, object] = {}

    class _Session:
        def __init__(self, path: str, providers: list[str] | None = None):
            seen["providers"] = providers

    class _Engine:
        @classmethod
        def from_session(cls, session: object, voices_path: str):
            return cls()

        async def create_stream(self, text: str, voice: str, speed: float, lang: str):
            seen["text"] = text
            seen["voice"] = voice
            yield [0.0, 0.5], 24000
            yield [-0.5], 24000

        def create(self, *_args, **_kwargs):
            raise AssertionError("one-shot create should not run for a stream")

    kokoro_onnx = ModuleType("kokoro_onnx")
    kokoro_onnx.Kokoro = _Engine  # type: ignore[attr-defined]
    onnxruntime = ModuleType("onnxruntime")
    onnxruntime.InferenceSession = _Session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kokoro_onnx", kokoro_onnx)
    monkeypatch.setitem(sys.modules, "onnxruntime", onnxruntime)
    wavs = list(KokoroTTS(model, voices, voice="af_heart").synthesize_stream("Hello there."))
    assert seen["text"] == "Hello there."
    assert seen["voice"] == "af_heart"
    assert len(wavs) == 2
    assert all(wav[:4] == b"RIFF" for wav in wavs)


def test_kokoro_voices_default_beside_the_model(tmp_path: Path) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    model.write_bytes(b"x")
    speaker = tts_from_settings(_Settings(kokoro=str(model), voice="am_adam"))
    assert speaker.model_path == model
    assert speaker.voices_path == tmp_path / "voices-v1.0.bin"
    assert speaker.voice == "am_adam"
    assert lang_for_voice("af_heart") == "en-us"
    assert lang_for_voice("bm_george") == "en-gb"


def test_kokoro_missing_model_or_voices(tmp_path: Path) -> None:
    voices = tmp_path / "voices-v1.0.bin"
    voices.write_bytes(b"voices")
    with pytest.raises(SpeechNotConfigured):
        KokoroTTS(tmp_path / "missing.onnx", voices).synthesize("Hello")
    model = tmp_path / "kokoro-v1.0.onnx"
    model.write_bytes(b"model")
    with pytest.raises(SpeechNotConfigured):
        KokoroTTS(model, tmp_path / "missing.bin").synthesize("Hello")


def test_voice_extra_uses_kokoro_not_future_engines() -> None:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    voice = text.split("voice = [", 1)[1].split("]", 1)[0].lower()
    assert "kokoro-onnx" in voice
    assert "vosk" in voice
    assert "piper-tts" not in voice
    assert "faster-whisper" not in voice


@pytest.mark.voice_live
def test_vosk_live_silence() -> None:
    model = os.environ.get("SPEECH_STT_MODEL", "").strip()
    if not model:
        pytest.skip("Set SPEECH_STT_MODEL to an unpacked Vosk model")
    pytest.importorskip("vosk")
    text = VoskSpeechToText(Path(model)).transcribe(b"\x00\x00" * 16_000, sample_rate=16_000)
    assert isinstance(text, str)


@pytest.mark.voice_live
def test_kokoro_live_cpu_smoke() -> None:
    model = os.environ.get("SPEECH_TTS_MODEL", "").strip()
    if not model:
        pytest.skip("Set SPEECH_TTS_MODEL to kokoro-v1.0.onnx")
    pytest.importorskip("kokoro_onnx")
    voices = os.environ.get("SPEECH_KOKORO_VOICES", "").strip()
    voice = os.environ.get("SPEECH_KOKORO_VOICE", "").strip() or "af_heart"
    speaker = tts_from_settings(_Settings(kokoro=model, voices=voices, voice=voice))
    wav = speaker.synthesize("Hello from the voice prototype.")
    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 24_000
        assert handle.getnframes() > 0
