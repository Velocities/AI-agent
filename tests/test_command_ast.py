import pytest

from ai_agent.commands.ast import parse_command_expr


def test_find_exec_missing_terminator_rejected_at_parse() -> None:
    with pytest.raises(ValueError, match="find -exec"):
        parse_command_expr(
            {
                "type": "single",
                "argv": ["find", ".", "-exec", "grep", "-l", "temperature"],
            }
        )


def test_find_exec_semicolon_terminator_rejected_at_parse() -> None:
    with pytest.raises(ValueError, match="find -exec"):
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
                    "{}",
                    ";",
                ],
            }
        )


def test_find_exec_parses_with_plus_terminator() -> None:
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
    assert expr.argv[-2:] == ["{}", "+"]
