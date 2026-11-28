"""Add the shared database URL and catalog root to .env when those lines are missing.

Existing non-empty values are left alone. The installer calls this so the
service and the admin CLI share one database and one workflow catalog.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def ensure(env_path: Path, shared_url: str, catalog: str) -> None:
    text = env_path.read_text(encoding="utf-8")
    changed = False
    if not re.search(r"^CONVERSATION_DATABASE=\S", text, re.MULTILINE):
        if re.search(r"^CONVERSATION_DATABASE=\s*$", text, re.MULTILINE):
            text = re.sub(
                r"^CONVERSATION_DATABASE=\s*$",
                f"CONVERSATION_DATABASE={shared_url}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            if not text.endswith("\n"):
                text += "\n"
            text += (
                "\n# Shared by systemd (user ai) and admin CLI — do not use per-login paths.\n"
                f"CONVERSATION_DATABASE={shared_url}\n"
            )
        changed = True
        print(f"Set CONVERSATION_DATABASE in {env_path} to the shared deployment database.")
    if not re.search(r"^WORKFLOW_CATALOG_ROOT=\S", text, re.MULTILINE):
        if not text.endswith("\n"):
            text += "\n"
        text += f"WORKFLOW_CATALOG_ROOT={catalog}\n"
        changed = True
        print(f"Set WORKFLOW_CATALOG_ROOT in {env_path} to {catalog}.")
    if changed:
        env_path.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: ensure_env.py ENV_PATH SHARED_DB_URL CATALOG_ROOT",
            file=sys.stderr,
        )
        return 2
    ensure(Path(argv[0]), argv[1], argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
