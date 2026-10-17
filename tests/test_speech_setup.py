"""Kokoro-82M download command. No network."""

from __future__ import annotations

from ai_agent.cli.config_cmd import main as config_main
from ai_agent.speech.tts.kokoro_assets import (
    KokoroAsset,
    KokoroDownloadError,
    install_kokoro_assets,
)


class _Response:
    def __init__(self, payload: bytes, length: int | None = None):
        self.headers = {"Content-Length": str(len(payload) if length is None else length)}
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0 or size >= len(self._payload):
            data = self._payload
            self._payload = b""
            return data
        data = self._payload[:size]
        self._payload = self._payload[size:]
        return data


def test_install_downloads_then_skips_a_complete_file(tmp_path) -> None:
    bodies = {
        "kokoro-v1.0.onnx": b"onnx-bytes",
        "voices-v1.0.bin": b"voices",
    }
    calls: list[str] = []

    def urlopen(request, timeout: int = 60):
        calls.append(request.get_method())
        name = request.full_url.rsplit("/", 1)[-1]
        return _Response(bodies[name])

    dest = tmp_path / "voice"
    first = install_kokoro_assets(dest, urlopen=urlopen)
    assert [asset.downloaded for asset in first] == [True, True]
    assert (dest / "kokoro-v1.0.onnx").read_bytes() == b"onnx-bytes"
    assert (dest / "voices-v1.0.bin").read_bytes() == b"voices"
    assert not list(dest.glob("*.partial"))
    done = len(calls)
    second = install_kokoro_assets(dest, urlopen=urlopen)
    assert [asset.downloaded for asset in second] == [False, False]
    assert calls[done:] == ["HEAD", "HEAD"]


def test_install_rejects_a_short_download(tmp_path) -> None:
    def urlopen(request, timeout: int = 60):
        name = request.full_url.rsplit("/", 1)[-1]
        if request.get_method() == "HEAD":
            return _Response(b"x" * 8)
        return _Response(b"short", length=8)

    try:
        install_kokoro_assets(tmp_path / "voice", urlopen=urlopen)
    except KokoroDownloadError as exc:
        assert "stopped early" in str(exc)
    else:
        raise AssertionError("short download should fail")
    assert not list((tmp_path / "voice").glob("*.partial"))


def test_config_speech_setup_prints_the_env_line(tmp_path, capsys) -> None:
    model = (tmp_path / "kokoro-v1.0.onnx").resolve()
    voices = (tmp_path / "voices-v1.0.bin").resolve()

    def fake_install(dest):
        return [KokoroAsset(model, True), KokoroAsset(voices, False)]

    import ai_agent.cli.speech_cmd as speech_cmd

    original = speech_cmd.install_kokoro_assets
    speech_cmd.install_kokoro_assets = fake_install
    try:
        assert config_main(["speech", "setup", "--dest", str(tmp_path)]) == 0
    finally:
        speech_cmd.install_kokoro_assets = original
    out = capsys.readouterr().out
    assert f"SPEECH_TTS_MODEL={model}" in out
    assert "pip install -e '.[voice]'" in out
    assert "already present" in out


def test_config_speech_setup_reports_a_download_failure(tmp_path, capsys) -> None:
    import ai_agent.cli.speech_cmd as speech_cmd

    def boom(_dest):
        raise KokoroDownloadError("network down")

    original = speech_cmd.install_kokoro_assets
    speech_cmd.install_kokoro_assets = boom
    try:
        assert config_main(["speech", "setup", "--dest", str(tmp_path)]) == 1
    finally:
        speech_cmd.install_kokoro_assets = original
    assert "network down" in capsys.readouterr().out
