from pathlib import Path

from ai_agent.agent.loop import AgentLoop
from ai_agent.commands.ast import parse_command_expr
from ai_agent.commands.executor import CommandExecutor
from ai_agent.commands.render import render_write_file
from ai_agent.config import Settings
from ai_agent.policy.engine import PolicyEngine
from ai_agent.policy.risk import RiskLevel


def test_write_file_render_hides_body_but_shows_metadata() -> None:
    expr = parse_command_expr(
        {
            "type": "write_file",
            "path": "/home/user/project/gpu.py",
            "content": "def main():\n    pass\n",
        }
    )
    rendered = render_write_file(expr)
    assert "write_file" in rendered
    assert "--truncate" in rendered
    assert "/home/user/project/gpu.py" in rendered
    assert "--bytes" in rendered
    assert "def main" not in rendered or "# preview:" in rendered


def test_write_file_executes_without_shell(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out.txt"
    expr = parse_command_expr(
        {
            "type": "write_file",
            "path": str(target),
            "content": "hello\n",
        }
    )
    executor = CommandExecutor(timeout=5, output_limit=1024, scratch_dir=tmp_path)
    result = executor.run(expr)
    assert result.success
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_write_file_policy_is_reversible() -> None:
    expr = parse_command_expr(
        {
            "type": "write_file",
            "path": "/tmp/x",
            "content": "x",
        }
    )
    engine = PolicyEngine.from_yaml(Settings().policy_path(), None)
    decision = engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.REVERSIBLE


def test_parse_accepts_write_file_with_semicolons_in_content() -> None:
    expr, err = AgentLoop._parse_command_for_tool(
        {
            "type": "write_file",
            "path": "/tmp/a.py",
            "content": "a = 1; b = 2\n",
        }
    )
    assert err is None
    assert expr is not None
