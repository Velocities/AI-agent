from __future__ import annotations

from pathlib import Path

MAX_WRITE_BYTES = 512_000


def perform_write_file(
    path: str,
    content: str,
    *,
    append: bool = False,
    max_bytes: int = MAX_WRITE_BYTES,
) -> tuple[int, str, str]:
    """Write UTF-8 text to path (no shell). Returns (exit_code, stdout, stderr)."""
    if "\0" in path or "\0" in content:
        return 1, "", "NUL bytes are not allowed in path or content"
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        return (
            1,
            "",
            f"Content exceeds write limit ({len(encoded)} > {max_bytes} bytes)",
        )
    target = Path(path).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8") as handle:
            handle.write(content)
    except OSError as exc:
        return 1, "", str(exc)
    action = "appended" if append else "wrote"
    return 0, f"{action} {len(encoded)} bytes to {target}", ""
