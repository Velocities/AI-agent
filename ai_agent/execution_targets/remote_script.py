from __future__ import annotations

from ai_agent.commands.ast import (
    AndCommand,
    CommandExpr,
    OrCommand,
    PipeCommand,
    RedirectCommand,
    SingleCommand,
)


def posix_quote(value: str) -> str:
    """Quote a string for a POSIX shell. Independent of the agent host OS."""
    return "'" + value.replace("'", "'\\''") + "'"


def render_posix_script(expr: CommandExpr) -> str:
    """Build a remote/container script from a structured expression.

    Operators come from the AST. Every argv element and path is quoted so
    model-supplied text cannot become extra shell syntax.
    """
    return _render(expr)


def _render(expr: CommandExpr) -> str:
    if isinstance(expr, SingleCommand):
        command = " ".join(posix_quote(part) for part in expr.argv)
        if expr.cwd:
            return f"cd {posix_quote(expr.cwd)} && {command}"
        return command
    if isinstance(expr, PipeCommand):
        left = _wrap_if_needed(expr.left)
        right = " ".join(posix_quote(part) for part in expr.right_argv)
        return f"{left} | {right}"
    if isinstance(expr, AndCommand):
        return f"{_wrap_if_needed(expr.left)} && {_wrap_if_needed(expr.right)}"
    if isinstance(expr, OrCommand):
        return f"{_wrap_if_needed(expr.left)} || {_wrap_if_needed(expr.right)}"
    if isinstance(expr, RedirectCommand):
        posix_path = expr.path.replace("\\", "/")
        parent = posix_path.rsplit("/", 1)[0] if "/" in posix_path else "."
        inner = f"{_wrap_if_needed(expr.cmd)} {expr.op} {posix_quote(expr.path)}"
        if parent in {"", "."}:
            return inner
        return f"mkdir -p {posix_quote(parent)} && {inner}"
    raise TypeError(f"Unsupported expression: {type(expr)!r}")


def _wrap_if_needed(expr: CommandExpr) -> str:
    rendered = _render(expr)
    if isinstance(expr, (AndCommand, OrCommand, RedirectCommand)):
        return f"({rendered})"
    return rendered
