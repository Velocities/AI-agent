from __future__ import annotations

import shlex

from ai_agent.commands.ast import (
    AndCommand,
    CommandExpr,
    OrCommand,
    PipeCommand,
    RedirectCommand,
    SingleCommand,
    WriteFileCommand,
)


def render_argv(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def render_command(expr: CommandExpr, *, wrap: bool = False) -> str:
    rendered = _render(expr)
    if wrap:
        return f"({rendered})"
    return rendered


def _render(expr: CommandExpr) -> str:
    if isinstance(expr, SingleCommand):
        text = render_argv(expr.argv)
        if expr.cwd:
            return f"{text}  # cwd={expr.cwd}"
        return text
    if isinstance(expr, PipeCommand):
        left = _render(expr.left)
        if isinstance(expr.left, (AndCommand, OrCommand, RedirectCommand)):
            left = f"({left})"
        return f"{left} | {render_argv(expr.right_argv)}"
    if isinstance(expr, AndCommand):
        return f"{_wrap(expr.left)} && {_wrap(expr.right)}"
    if isinstance(expr, OrCommand):
        return f"{_wrap(expr.left)} || {_wrap(expr.right)}"
    if isinstance(expr, RedirectCommand):
        inner = _wrap(expr.cmd)
        return f"{inner} {expr.op} {shlex.quote(expr.path)}"
    if isinstance(expr, WriteFileCommand):
        return render_write_file(expr)
    raise TypeError(f"Unknown expression: {type(expr)!r}")


def render_write_file(expr: WriteFileCommand) -> str:
    """Human-readable approval line; file body is not echoed (injection-safe display)."""
    mode = "--append" if expr.append else "--truncate"
    byte_count = len(expr.content.encode("utf-8"))
    line_count = expr.content.count("\n") + (1 if expr.content else 0)
    preview = _content_preview(expr.content)
    parts = [
        "write_file",
        mode,
        f"--path {shlex.quote(expr.path)}",
        f"--bytes {byte_count}",
        f"--lines {line_count}",
    ]
    if preview:
        parts.append(f"# preview: {shlex.quote(preview)}")
    return " ".join(parts)


def _content_preview(content: str, limit: int = 72) -> str:
    single = content.replace("\n", "\\n").replace("\r", "")
    if len(single) <= limit:
        return single
    return single[: limit - 3] + "..."


def _wrap(expr: CommandExpr) -> str:
    if isinstance(expr, (SingleCommand, PipeCommand)):
        return _render(expr)
    return f"({_render(expr)})"
