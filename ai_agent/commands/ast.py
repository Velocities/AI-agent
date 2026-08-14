from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator


class SingleCommand(BaseModel):
    type: Literal["single"] = "single"
    argv: list[str]
    cwd: str | None = None

    @field_validator("argv")
    @classmethod
    def argv_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("argv must not be empty")
        return value


class PipeCommand(BaseModel):
    type: Literal["pipe"] = "pipe"
    left: "CommandExpr"
    right_argv: list[str] = Field(alias="right")

    model_config = {"populate_by_name": True}

    @field_validator("right_argv")
    @classmethod
    def right_argv_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("right argv must not be empty")
        return value


class AndCommand(BaseModel):
    type: Literal["and"] = "and"
    left: "CommandExpr"
    right: "CommandExpr"


class OrCommand(BaseModel):
    type: Literal["or"] = "or"
    left: "CommandExpr"
    right: "CommandExpr"


class RedirectCommand(BaseModel):
    type: Literal["redirect"] = "redirect"
    cmd: "CommandExpr"
    op: Literal[">", ">>", "2>"]
    path: str


CommandExpr = Annotated[
    Union[SingleCommand, PipeCommand, AndCommand, OrCommand, RedirectCommand],
    Field(discriminator="type"),
]

PipeCommand.model_rebuild()
AndCommand.model_rebuild()
OrCommand.model_rebuild()
RedirectCommand.model_rebuild()


def iter_leaves(expr: CommandExpr) -> list[SingleCommand]:
    """Return every executable leaf as a SingleCommand."""
    if isinstance(expr, SingleCommand):
        return [expr]
    if isinstance(expr, PipeCommand):
        return iter_leaves(expr.left)
    if isinstance(expr, AndCommand):
        return iter_leaves(expr.left) + iter_leaves(expr.right)
    if isinstance(expr, OrCommand):
        return iter_leaves(expr.left) + iter_leaves(expr.right)
    if isinstance(expr, RedirectCommand):
        return iter_leaves(expr.cmd)
    raise TypeError(f"Unknown command expression type: {type(expr)!r}")


def iter_pipe_segments(expr: CommandExpr) -> list[list[str]]:
    """Return argv lists for each segment in a pipe chain."""
    if isinstance(expr, SingleCommand):
        return [expr.argv]
    if isinstance(expr, PipeCommand):
        return iter_pipe_segments(expr.left) + [expr.right_argv]
    raise ValueError("iter_pipe_segments only supports single commands and pipes")


def parse_command_expr(data: dict) -> CommandExpr:
    return _CommandExprAdapter.validate_python(data)


class _CommandExprAdapter(BaseModel):
    root: CommandExpr

    @classmethod
    def validate_python(cls, data: dict) -> CommandExpr:
        if data.get("type") == "pipe" and "right" in data and "right_argv" not in data:
            data = {**data, "right_argv": data["right"]}
        if data.get("type") == "pipe" and isinstance(data.get("right"), dict):
            raise ValueError("pipe.right must be an argv list, not a nested expression")
        return cls.model_validate({"root": data}).root
