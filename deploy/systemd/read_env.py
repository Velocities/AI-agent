"""Print one value from a .env file. Missing keys print an empty line."""

from __future__ import annotations

import sys
from pathlib import Path


def read_value(env_path: Path, key: str) -> str:
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: read_env.py ENV_PATH KEY", file=sys.stderr)
        return 2
    print(read_value(Path(argv[0]), argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
