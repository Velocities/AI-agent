"""Download the Kokoro-82M ONNX weights used by KokoroTTS."""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

KOKORO_RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)
KOKORO_MODEL_NAME = "kokoro-v1.0.onnx"
KOKORO_VOICES_NAME = "voices-v1.0.bin"
KOKORO_ASSETS = (
    (f"{KOKORO_RELEASE}/{KOKORO_MODEL_NAME}", KOKORO_MODEL_NAME),
    (f"{KOKORO_RELEASE}/{KOKORO_VOICES_NAME}", KOKORO_VOICES_NAME),
)


class KokoroDownloadError(Exception):
    """The Kokoro-82M weights could not be downloaded."""


@dataclass(frozen=True)
class KokoroAsset:
    path: Path
    downloaded: bool


def install_kokoro_assets(
    dest: Path,
    *,
    urlopen=urllib.request.urlopen,
) -> list[KokoroAsset]:
    """Download Kokoro-82M into dest. A file whose size matches the release is kept."""
    destination = Path(dest)
    destination.mkdir(parents=True, exist_ok=True)
    installed: list[KokoroAsset] = []
    for url, name in KOKORO_ASSETS:
        target = destination / name
        downloaded = _ensure_asset(url, target, urlopen)
        installed.append(KokoroAsset(path=target.resolve(), downloaded=downloaded))
    return installed


def _ensure_asset(url: str, target: Path, urlopen) -> bool:
    expected = _content_length(url, urlopen)
    if target.is_file() and expected and target.stat().st_size == expected:
        return False
    partial = target.with_name(target.name + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "ai-agent"})
    try:
        with urlopen(request, timeout=120) as response:
            length = int(response.headers.get("Content-Length") or expected or 0)
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise KokoroDownloadError(f"Could not download {url}: {exc}") from exc
    got = partial.stat().st_size
    if length and got != length:
        partial.unlink(missing_ok=True)
        raise KokoroDownloadError(
            f"Download of {target.name} stopped early ({got} of {length} bytes)."
        )
    partial.replace(target)
    return True


def _content_length(url: str, urlopen) -> int:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "ai-agent"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return int(response.headers.get("Content-Length") or 0)
    except Exception as exc:
        raise KokoroDownloadError(f"Could not check {url}: {exc}") from exc
