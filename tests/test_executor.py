import platform
from pathlib import Path

import pytest

from ai_agent.commands.ast import parse_command_expr
from ai_agent.commands.executor import CommandExecutor


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows PowerShell test")
def test_powershell_runs_with_safe_env(tmp_path: Path) -> None:
    executor = CommandExecutor(
        timeout=30,
        output_limit=32768,
        scratch_dir=tmp_path / "scratch",
    )
    expr = parse_command_expr(
        {
            "type": "single",
            "argv": [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-ChildItem",
                "-LiteralPath",
                str(Path.cwd()),
                "-Name",
            ],
        }
    )
    result = executor.run(expr)
    assert result.success, result.stderr
    assert "README.md" in result.stdout
