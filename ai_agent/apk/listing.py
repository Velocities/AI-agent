"""HTML index of published APKs, in the shape of a directory listing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_APK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}\.apk$")


@dataclass(frozen=True)
class ApkFile:
    name: str
    size_bytes: int
    modified: datetime


def format_modified(when: datetime) -> str:
    """Weekday, calendar date, clock time, and numeric offset."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone().strftime("%A, %Y-%m-%d %H:%M:%S %z")


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    value = float(size_bytes)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{size_bytes} B"


_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
_env.filters["format_modified"] = format_modified
_env.filters["format_size"] = format_size


def list_apk_files(directory: Path) -> list[ApkFile]:
    """APK files directly inside ``directory``, newest modification time first."""
    if not directory.is_dir():
        return []
    root = directory.resolve()
    files: list[ApkFile] = []
    for path in directory.iterdir():
        if not _APK_NAME.fullmatch(path.name):
            continue
        resolved = path.resolve()
        if resolved.parent != root or not resolved.is_file():
            continue
        stat = resolved.stat()
        files.append(
            ApkFile(
                name=path.name,
                size_bytes=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )
    files.sort(key=lambda item: (item.modified, item.name), reverse=True)
    return files


def resolve_published_apk(directory: Path, name: str) -> Path | None:
    """Return the file for ``name``, or None when it is not one APK in ``directory``."""
    if not _APK_NAME.fullmatch(name):
        return None
    root = directory.resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        return None
    return path


def render_apk_listing_folder(files: list[ApkFile]) -> str:
    return _env.get_template("index.html").render(files=files)
