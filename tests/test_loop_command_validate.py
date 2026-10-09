from ai_agent.agent.loop import AgentLoop


def test_parse_command_for_tool_rejects_broken_find_exec() -> None:
    _, err = AgentLoop._parse_command_for_tool(
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
    assert err is not None
    assert "find -exec" in err.lower()


def test_parse_command_for_tool_rejects_semicolon_chain() -> None:
    _, err = AgentLoop._parse_command_for_tool(
        {"type": "single", "argv": ["echo", "a", ";", "echo", "b"]},
    )
    assert err is not None
    assert "Semicolon" in err


def test_parse_command_for_tool_rejects_semicolon_inside_argv_string() -> None:
    _, err = AgentLoop._parse_command_for_tool(
        {"type": "single", "argv": ["echo", "hello;world"]},
    )
    assert err is not None
    assert "Semicolon" in err


def test_parse_command_for_tool_accepts_find_exec_plus() -> None:
    expr, err = AgentLoop._parse_command_for_tool(
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
    assert err is None
    assert expr is not None


def test_parse_command_for_tool_accepts_grep_batch_shapes() -> None:
    for data in (
        {"type": "single", "argv": ["grep", "-R", "-l", "stub", "--include=*.py", "."]},
        {"type": "single", "argv": ["grep", "-R", "-n", "temperature", "--include=*.py", "."]},
    ):
        expr, err = AgentLoop._parse_command_for_tool(data)
        assert err is None
        assert expr is not None
