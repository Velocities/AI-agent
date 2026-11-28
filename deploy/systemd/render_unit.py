"""Fill a systemd unit template and write the unit file.

Each argument after the destination is a placeholder assignment,
``@NAME@=value``. ``%`` in a value is written as ``%%`` because systemd
treats ``%`` as a specifier.
"""

from __future__ import annotations

import sys
from pathlib import Path


def render(template: Path, dest: Path, replacements: dict[str, str]) -> None:
    text = template.read_text(encoding="utf-8")
    for key, value in replacements.items():
        if key not in text:
            raise SystemExit(f"template is missing {key}")
        text = text.replace(key, value.replace("%", "%%"))
    dest.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: render_unit.py TEMPLATE DEST @PLACEHOLDER@=value ...",
            file=sys.stderr,
        )
        return 2
    template = Path(argv[0])
    dest = Path(argv[1])
    replacements: dict[str, str] = {}
    for pair in argv[2:]:
        if "=" not in pair:
            print(f"expected @PLACEHOLDER@=value, got {pair!r}", file=sys.stderr)
            return 2
        key, value = pair.split("=", 1)
        replacements[key] = value
    render(template, dest, replacements)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
