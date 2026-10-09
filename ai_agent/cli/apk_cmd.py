"""Copy a debug APK into the directory served by the admin download page.

Build with Gradle first (``./gradlew :app:assembleDebug`` in ``clients/android``).
This command only copies the APK. It does not invoke Gradle.

Set ``APK_PUBLISH_DIR`` to the destination. The download page stays off until
``APK_DOWNLOADS_ENABLED=true``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from ai_agent.apk.publish import locate_debug_apk, publish_apk
from ai_agent.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-agent apk",
        description="Publish a debug APK for admin download on this deployment.",
    )
    sub = parser.add_subparsers(dest="command")
    publish = sub.add_parser(
        "publish",
        help="Copy the Gradle debug APK into APK_PUBLISH_DIR.",
    )
    publish.add_argument(
        "--apk",
        type=Path,
        default=None,
        help="APK to copy. Default: the Gradle debug output under this checkout.",
    )

    args = parser.parse_args(argv)
    if args.command != "publish":
        parser.print_help()
        return 0 if args.command is None else 2

    out = Console()
    err = Console(stderr=True)
    settings = Settings()
    raw_dir = settings.apk_publish_dir.strip()
    if not raw_dir:
        err.print("Set APK_PUBLISH_DIR to the directory that should store published APKs.")
        return 1

    try:
        source = args.apk.expanduser() if args.apk is not None else locate_debug_apk()
        result = publish_apk(source, Path(raw_dir).expanduser())
    except (FileNotFoundError, ValueError) as exc:
        err.print(str(exc))
        return 1

    out.print(f"Published {result.path}")
    if result.warning:
        err.print(
            f"Warning: {result.path.parent} has {result.count} APK files. "
            "Older builds take disk space; delete the ones you no longer need."
        )
    return 0
