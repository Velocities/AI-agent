import pytest
from pydantic import ValidationError

from ai_agent.commands.ast import parse_command_expr
from ai_agent.commands.validate import command_expression_issue
from ai_agent.config import Settings
from ai_agent.policy.engine import PolicyEngine


def test_find_exec_with_plus_is_allowed(tmp_path) -> None:
    expr = parse_command_expr(
        {
            "type": "single",
            "argv": [
                "find",
                ".",
                "-name",
                "*.py",
                "-exec",
                "grep",
                "-l",
                "temperature",
                "{}",
                "+",
            ],
        }
    )
    assert command_expression_issue(expr) is None
    engine = PolicyEngine.from_yaml(Settings().policy_path(), tmp_path)
    assert engine.evaluate(expr).allowed


def test_find_exec_semicolon_terminator_forbidden() -> None:
    with pytest.raises(ValidationError, match="find -exec"):
        parse_command_expr(
            {
                "type": "single",
                "argv": ["find", ".", "-exec", "grep", "-l", "x", "{}", ";"],
            }
        )


def test_find_exec_missing_terminator_rejected_at_parse() -> None:
    with pytest.raises(ValidationError, match="find -exec"):
        parse_command_expr(
            {
                "type": "single",
                "argv": [
                    "find",
                    ".",
                    "-name",
                    "*.py",
                    "-exec",
                    "grep",
                    "-l",
                    "temperature",
                ],
            }
        )


def test_semicolon_inside_argv_string_forbidden() -> None:
    expr = parse_command_expr(
        {"type": "single", "argv": ["echo", "hello;rm -rf /"]},
    )
    assert command_expression_issue(expr) is not None


def test_lone_semicolon_without_find_exec_forbidden() -> None:
    argv = ["echo", "a", ";", "echo", "b"]
    assert PolicyEngine.forbidden_semicolon_usage(argv)


def test_grep_batch_via_run_commands_shape() -> None:
    for data in (
        {"type": "single", "argv": ["grep", "-R", "-l", "stub", "--include=*.py", "."]},
        {"type": "single", "argv": ["grep", "-R", "-l", "temperature", "--include=*.py", "."]},
    ):
        expr = parse_command_expr(data)
        assert command_expression_issue(expr) is None
