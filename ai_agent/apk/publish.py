"""Copy a Gradle debug APK into the deployment publish directory.

``ai-agent apk publish`` is separate from ``./gradlew :app:assembleDebug``.
The Gradle build writes ``app-debug.apk``; this module copies that file under
a new name so older builds stay in the directory.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

STORAGE_WARNING_COUNT = 10

_DEBUG_APK_CANDIDATES = (
    Path("clients/android/app/build/outputs/apk/debug/app-debug.apk"),
    Path("app/build/outputs/apk/debug/app-debug.apk"),
)
_STEM = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class PublishResult:
    path: Path
    count: int
    warning: bool


def locate_debug_apk(start: Path | None = None) -> Path:
    """Find the Gradle debug APK by walking up from ``start`` (default: cwd)."""
    cursor = (start or Path.cwd()).resolve()
    directories = [cursor, *cursor.parents]
    for directory in directories:
        for relative in _DEBUG_APK_CANDIDATES:
            candidate = directory / relative
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(
        "No debug APK found. Build one with ./gradlew :app:assembleDebug "
        "in clients/android, then run ai-agent apk publish."
    )


def publish_apk(
    source: Path,
    directory: Path,
    *,
    now: datetime | None = None,
) -> PublishResult:
    """Copy ``source`` into ``directory`` without removing existing APKs.

    ``warning`` is true once the directory holds ``STORAGE_WARNING_COUNT`` or
    more ``.apk`` files, including the one just copied.
    """
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"APK not found: {source}")
    if source.suffix.lower() != ".apk":
        raise ValueError(f"Not an APK file: {source}")

    directory.mkdir(parents=True, exist_ok=True)
    when = now if now is not None else datetime.now().astimezone()
    destination = _unique_destination(directory, source.stem, when)
    shutil.copy2(source, destination)
    count = sum(1 for _ in _apk_paths(directory))
    return PublishResult(
        path=destination,
        count=count,
        warning=count >= STORAGE_WARNING_COUNT,
    )


def _unique_destination(directory: Path, stem: str, when: datetime) -> Path:
    safe_stem = _STEM.sub("-", stem).strip(".-") or "app"
    stamp = when.strftime("%Y%m%d-%H%M%S")
    candidate = directory / f"{safe_stem}-{stamp}.apk"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{safe_stem}-{stamp}-{suffix}.apk"
        suffix += 1
    return candidate


def _apk_paths(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix == ".apk")
