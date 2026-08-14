from __future__ import annotations

import shlex

from ai_agent.commands.ast import (
    AndCommand,
    CommandExpr,
    OrCommand,
    PipeCommand,
    RedirectCommand,
    SingleCommand,
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
    raise TypeError(f"Unknown expression: {type(expr)!r}")


def _wrap(expr: CommandExpr) -> str:
    if isinstance(expr, (SingleCommand, PipeCommand)):
        return _render(expr)
    return f"({_render(expr)})"
