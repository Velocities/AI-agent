"""Run as the target Linux user: read file body from stdin, write to argv[1]."""

from __future__ import annotations

import sys

from ai_agent.commands.write_file import perform_write_file


def main() -> int:
    args = sys.argv[1:]
    append = False
    if "--append" in args:
        append = True
        args = [part for part in args if part != "--append"]
    if len(args) != 1:
        print("usage: write_file_entry [--append] PATH", file=sys.stderr)
        return 2
    code, _stdout, stderr = perform_write_file(
        args[0],
        sys.stdin.read(),
        append=append,
    )
    if stderr:
        print(stderr, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
