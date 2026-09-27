from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from pathlib import Path

from ai_agent.commands.ast import CommandExpr
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.deployment.identity import normalize_linux_username


class RunAsCommandExecutor(CommandExecutor):
    """Run local commands as a specific Linux user (API service drops from `ai`)."""

    def __init__(
        self,
        timeout: int,
        output_limit: int,
        scratch_dir: Path,
        *,
        linux_username: str,
    ):
        super().__init__(timeout, output_limit, scratch_dir)
        self._linux_username = normalize_linux_username(linux_username)
        self._passwd = pwd.getpwnam(self._linux_username)

    def run(self, expr: CommandExpr) -> CommandResult:
        result = super().run(expr)
        meta = {**(result.metadata or {}), "run_as_linux_user": self._linux_username}
        result.metadata = meta
        return result

    def _run_single(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        stdin: subprocess.PIPE | None = None,
        stdout: subprocess.PIPE | None = subprocess.PIPE,
        stderr: subprocess.PIPE | None = subprocess.PIPE,
    ) -> tuple[int, str, str]:
        if _runs_as_current_user(self._linux_username):
            return super()._run_single(
                argv,
                cwd=cwd,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
        wrapped, env = _wrap_argv_for_user(argv, self._passwd)
        completed = subprocess.run(
            wrapped,
            cwd=cwd or self._passwd.pw_dir,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            text=True,
            timeout=self.timeout,
            env=env,
        )
        return (
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )

    def _run_pipe(self, expr) -> tuple[int, str, str]:
        if _runs_as_current_user(self._linux_username):
            return super()._run_pipe(expr)
        from ai_agent.commands.ast import PipeCommand
        from ai_agent.commands.render import render_command

        if not isinstance(expr, PipeCommand):
            return super()._run_pipe(expr)
        rendered = render_command(expr)
        shell_argv = ["bash", "-lc", rendered]
        wrapped, env = _wrap_argv_for_user(shell_argv, self._passwd)
        completed = subprocess.run(
            wrapped,
            cwd=self._passwd.pw_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self.timeout,
            env=env,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or ""

    def _safe_env(self) -> dict[str, str]:
        if _runs_as_current_user(self._linux_username):
            return super()._safe_env()
        return _env_for_passwd(self._passwd)


def build_command_executor(
    *,
    timeout: int,
    output_limit: int,
    scratch_dir: Path,
    linux_username: str | None,
) -> CommandExecutor:
    if linux_username and not _runs_as_current_user(linux_username):
        return RunAsCommandExecutor(
            timeout,
            output_limit,
            scratch_dir,
            linux_username=linux_username,
        )
    return CommandExecutor(timeout, output_limit, scratch_dir)


def _runs_as_current_user(linux_username: str) -> bool:
    try:
        return pwd.getpwuid(os.getuid()).pw_name == linux_username.strip().lower()
    except KeyError:
        return False


def _wrap_argv_for_user(argv: list[str], account: pwd.struct_passwd) -> tuple[list[str], dict[str, str]]:
    setpriv = shutil.which("setpriv")
    if setpriv:
        wrapped = [
            setpriv,
            f"--reuid={account.pw_uid}",
            f"--regid={account.pw_gid}",
            "--init-groups",
            "--",
            *argv,
        ]
        return wrapped, _env_for_passwd(account)

    runuser = shutil.which("runuser")
    if runuser:
        wrapped = [runuser, "-u", account.pw_name, "--", *argv]
        return wrapped, _env_for_passwd(account)

    sudo = shutil.which("sudo")
    if sudo:
        wrapped = [sudo, "-n", "-u", account.pw_name, "--", *argv]
        return wrapped, _env_for_passwd(account)

    raise OSError(
        f"Cannot run commands as {account.pw_name}: need setpriv, runuser, or passwordless sudo."
    )


def _env_for_passwd(account: pwd.struct_passwd) -> dict[str, str]:
    home = account.pw_dir or "/"
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return {
        "HOME": home,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "PATH": path,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", ""),
        "TERM": os.environ.get("TERM", "dumb"),
    }

