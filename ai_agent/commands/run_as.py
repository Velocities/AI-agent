from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import sys

from ai_agent.commands.ast import CommandExpr, RedirectCommand, WriteFileCommand
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.execution_targets.remote_script import render_posix_script
from ai_agent.deployment.identity import normalize_linux_username

# Same order as getpass.getuser(), without importing the Unix-only pwd module
# until a command actually has to switch Linux accounts.
_USER_ENV_VARS = ("LOGNAME", "USER", "LNAME", "USERNAME")


@dataclass(frozen=True)
class PosixAccount:
    name: str
    uid: int
    gid: int
    home: str


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
        self._account = lookup_posix_account(self._linux_username)

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
        wrapped, env = _wrap_argv_for_user(argv, self._account)
        completed = subprocess.run(
            wrapped,
            cwd=cwd or self._account.home,
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
        wrapped, env = _wrap_argv_for_user(shell_argv, self._account)
        completed = subprocess.run(
            wrapped,
            cwd=self._account.home,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self.timeout,
            env=env,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or ""

    def _run_write_file(self, expr: WriteFileCommand) -> tuple[int, str, str]:
        if _runs_as_current_user(self._linux_username):
            return super()._run_write_file(expr)
        helper = [sys.executable, "-m", "ai_agent.commands.write_file_entry"]
        if expr.append:
            helper.append("--append")
        helper.append(expr.path)
        wrapped, env = _wrap_argv_for_user(helper, self._account)
        completed = subprocess.run(
            wrapped,
            input=expr.content,
            cwd=self._account.home,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self.timeout,
            env=env,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or ""

    def _run_redirect(self, expr: RedirectCommand) -> tuple[int, str, str]:
        if _runs_as_current_user(self._linux_username):
            return super()._run_redirect(expr)
        rendered = render_posix_script(expr)
        shell_argv = ["bash", "-lc", rendered]
        wrapped, env = _wrap_argv_for_user(shell_argv, self._account)
        completed = subprocess.run(
            wrapped,
            cwd=self._account.home,
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
        return _env_for_account(self._account)


def build_command_executor(
    *,
    timeout: int,
    output_limit: int,
    scratch_dir: Path,
    linux_username: str | None,
) -> CommandExecutor:
    if linux_username and os.name == "posix" and _posix_run_as_available():
        return RunAsCommandExecutor(
            timeout,
            output_limit,
            scratch_dir,
            linux_username=linux_username,
        )
    return CommandExecutor(timeout, output_limit, scratch_dir)


def _posix_run_as_available() -> bool:
    try:
        import pwd  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def lookup_posix_account(username: str) -> PosixAccount:
    """Resolve a Linux account. Importing this module does not require `pwd`."""
    try:
        import pwd
    except ModuleNotFoundError as exc:
        raise OSError(
            "Running commands as another Linux user is only supported on Linux."
        ) from exc
    try:
        account = pwd.getpwnam(username)
    except KeyError as exc:
        raise OSError(f"Linux user {username!r} does not exist.") from exc
    return PosixAccount(
        name=account.pw_name,
        uid=account.pw_uid,
        gid=account.pw_gid,
        home=account.pw_dir or "/",
    )


def _current_username() -> str | None:
    for name in _USER_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        import pwd
    except ModuleNotFoundError:
        return None
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return None
    try:
        return pwd.getpwuid(getuid()).pw_name
    except (KeyError, OSError):
        return None


def _runs_as_current_user(linux_username: str) -> bool:
    current = _current_username()
    if not current:
        return False
    return current.strip().lower() == linux_username.strip().lower()


def _wrap_argv_for_user(argv: list[str], account: PosixAccount) -> tuple[list[str], dict[str, str]]:
    setpriv = shutil.which("setpriv")
    if setpriv:
        wrapped = [
            setpriv,
            f"--reuid={account.uid}",
            f"--regid={account.gid}",
            "--init-groups",
            "--",
            *argv,
        ]
        return wrapped, _env_for_account(account)

    runuser = shutil.which("runuser")
    if runuser:
        wrapped = [runuser, "-u", account.name, "--", *argv]
        return wrapped, _env_for_account(account)

    sudo = shutil.which("sudo")
    if sudo:
        wrapped = [sudo, "-n", "-u", account.name, "--", *argv]
        return wrapped, _env_for_account(account)

    raise OSError(
        f"Cannot run commands as {account.name}: need setpriv, runuser, or passwordless sudo."
    )


def _env_for_account(account: PosixAccount) -> dict[str, str]:
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return {
        "HOME": account.home,
        "USER": account.name,
        "LOGNAME": account.name,
        "PATH": path,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", ""),
        "TERM": os.environ.get("TERM", "dumb"),
    }
