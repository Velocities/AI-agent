"""HTML index of published APKs, in the shape of a directory listing."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

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


def render_apk_index(files: list[ApkFile]) -> str:
    if files:
        rows = "\n".join(_row(item) for item in files)
    else:
        rows = '<tr><td colspan="3" class="empty">No APK files in this directory.</td></tr>'
    return _PAGE.format(rows=rows)


def _row(item: ApkFile) -> str:
    name = html.escape(item.name)
    href = html.escape("/api/apk/" + quote(item.name), quote=True)
    modified = html.escape(format_modified(item.modified))
    size = html.escape(format_size(item.size_bytes))
    return (
        f'<tr><td class="name"><a href="{href}">{name}</a></td>'
        f'<td class="modified">{modified}</td>'
        f'<td class="size">{size}</td></tr>'
    )


_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>APK builds</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0;
    font-family: system-ui, sans-serif;
    line-height: 1.4;
    background: #f6f7f9;
    color: #1c1c1c;
  }}
  main {{ max-width: 52rem; margin: 0 auto; padding: 1.5rem 1rem 3rem; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; margin: 0 0 0.25rem; }}
  p {{ margin: 0 0 1.25rem; color: #4b5563; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; }}
  th, td {{ text-align: left; padding: 0.7rem 0.8rem; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
  th {{ font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; color: #6b7280; }}
  a {{ color: #1d4ed8; text-decoration: none; word-break: break-all; }}
  a:hover {{ text-decoration: underline; }}
  .modified, .size {{ white-space: nowrap; }}
  .size {{ text-align: right; }}
  th.size {{ text-align: right; }}
  .empty {{ color: #6b7280; }}
  @media (max-width: 640px) {{
    table, tbody, tr {{ display: block; width: 100%; }}
    thead {{ display: none; }}
    tr {{ padding: 0.75rem 0; }}
    td {{ display: block; width: auto; border: 0; padding: 0.15rem 0.8rem; }}
    td.modified::before {{ content: "Modified "; color: #6b7280; }}
    td.size {{ text-align: left; }}
    td.size::before {{ content: "Size "; color: #6b7280; }}
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #111315; color: #f3f4f6; }}
    p, th, .empty, td.modified::before, td.size::before {{ color: #9ca3af; }}
    table {{ background: #1b1e22; }}
    th, td {{ border-bottom-color: #2e3338; }}
    a {{ color: #93c5fd; }}
  }}
</style>
</head>
<body>
<main>
<h1>Index of APK builds</h1>
<p>Debug packages on this server. The time is when each file was last modified.</p>
<table>
<thead>
<tr><th>Name</th><th>Last modified</th><th class="size">Size</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</main>
</body>
</html>
"""
