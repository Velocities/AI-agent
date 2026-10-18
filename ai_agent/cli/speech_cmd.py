"""Download Kokoro-82M weights for speech synthesis."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from ai_agent.speech.tts.kokoro_assets import KokoroDownloadError, install_kokoro_assets

DEFAULT_DEST = Path(".ai-agent") / "voice"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-agent config speech",
        description="Download speech models. Python packages stay a separate install.",
    )
    sub = parser.add_subparsers(dest="command")
    setup = sub.add_parser(
        "setup",
        help="Download Kokoro-82M (kokoro-v1.0.onnx and voices-v1.0.bin).",
    )
    setup.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"Directory for the model files (default: {DEFAULT_DEST}).",
    )
    args = parser.parse_args(argv)
    console = Console(soft_wrap=True)
    if args.command != "setup":
        parser.print_help()
        return 0
    try:
        assets = install_kokoro_assets(args.dest)
    except KokoroDownloadError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    model = next(asset for asset in assets if asset.path.name.endswith(".onnx"))
    for asset in assets:
        state = "downloaded" if asset.downloaded else "already present"
        console.print(f"{state}: {asset.path}")
    console.print()
    console.print("Add this to .env and restart the server:")
    console.print(f"SPEECH_TTS_MODEL={model.path}")
    console.print()
    console.print(
        "voices-v1.0.bin sits beside that file, so SPEECH_KOKORO_VOICES can stay unset."
    )
    console.print(
        "The voice packages are a separate install: pip install -e '.[voice]'",
        markup=False,
    )
    return 0
