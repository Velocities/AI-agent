import os
from unittest.mock import patch

import pytest

from ai_agent.commands.ast import SingleCommand
from ai_agent.commands.run_as import RunAsCommandExecutor, build_command_executor
from ai_agent.deployment.identity import normalize_linux_username


def test_run_as_reports_when_pwd_is_unavailable(tmp_path, monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pwd":
            raise ModuleNotFoundError("No module named 'pwd'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(OSError, match="only supported on Linux"):
        RunAsCommandExecutor(
            timeout=5,
            output_limit=1024,
            scratch_dir=tmp_path,
            linux_username="nobody",
        )


def test_run_as_wraps_with_setpriv(tmp_path) -> None:
    executor = RunAsCommandExecutor(
        timeout=5,
        output_limit=1024,
        scratch_dir=tmp_path,
        linux_username="nobody",
    )
    expr = SingleCommand(argv=["echo", "hi"])
    with patch("ai_agent.commands.run_as.shutil.which", return_value="/usr/bin/setpriv"):
        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "hi\n"
            run.return_value.stderr = ""
            result = executor.run(expr)
    assert result.success
    argv = run.call_args.args[0]
    assert argv[0] == "/usr/bin/setpriv"
    assert "nobody" in str(argv) or "--reuid=" in argv[1]


def test_normalize_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_linux_username("")
