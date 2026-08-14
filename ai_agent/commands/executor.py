from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ai_agent.commands.ast import (
    AndCommand,
    CommandExpr,
    OrCommand,
    PipeCommand,
    RedirectCommand,
    SingleCommand,
    iter_pipe_segments,
)
from ai_agent.commands.render import render_command


@dataclass
class CommandResult:
    success: bool
    exit_status: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool = False
    rendered: str = ""
    metadata: dict | None = None

    def as_tool_payload(self) -> dict:
        return {
            "success": self.success,
            "exit_status": self.exit_status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "rendered_command": self.rendered,
            "metadata": self.metadata or {},
        }


class CommandExecutor:
    def __init__(self, timeout: int, output_limit: int, scratch_dir: Path):
        self.timeout = timeout
        self.output_limit = output_limit
        self.scratch_dir = scratch_dir

    def run(self, expr: CommandExpr) -> CommandResult:
        rendered = render_command(expr)
        start = time.perf_counter()
        try:
            exit_status, stdout, stderr = self._execute(expr)
            duration_ms = int((time.perf_counter() - start) * 1000)
            stdout, stdout_truncated = self._limit_output(stdout)
            stderr, stderr_truncated = self._limit_output(stderr)
            return CommandResult(
                success=exit_status == 0,
                exit_status=exit_status,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                truncated=stdout_truncated or stderr_truncated,
                rendered=rendered,
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return CommandResult(
                success=False,
                exit_status=124,
                stdout="",
                stderr=f"Command timed out after {self.timeout}s",
                duration_ms=duration_ms,
                rendered=rendered,
            )
        except OSError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return CommandResult(
                success=False,
                exit_status=127,
                stdout="",
                stderr=str(exc),
                duration_ms=duration_ms,
                rendered=rendered,
            )

    def _execute(self, expr: CommandExpr) -> tuple[int, str, str]:
        if isinstance(expr, SingleCommand):
            return self._run_single(expr.argv, cwd=expr.cwd)
        if isinstance(expr, PipeCommand):
            return self._run_pipe(expr)
        if isinstance(expr, AndCommand):
            code, out, err = self._execute(expr.left)
            if code != 0:
                return code, out, err
            return self._execute(expr.right)
        if isinstance(expr, OrCommand):
            code, out, err = self._execute(expr.left)
            if code == 0:
                return code, out, err
            return self._execute(expr.right)
        if isinstance(expr, RedirectCommand):
            return self._run_redirect(expr)
        raise TypeError(f"Unsupported expression: {type(expr)!r}")

    def _run_single(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        stdin: subprocess.PIPE | None = None,
        stdout: subprocess.PIPE | None = subprocess.PIPE,
        stderr: subprocess.PIPE | None = subprocess.PIPE,
    ) -> tuple[int, str, str]:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            text=True,
            timeout=self.timeout,
            env=self._safe_env(),
        )
        return (
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )

    def _run_pipe(self, expr: PipeCommand) -> tuple[int, str, str]:
        segments = iter_pipe_segments(expr)
        if len(segments) == 1:
            return self._run_single(segments[0])

        processes: list[subprocess.Popen[str]] = []
        previous_stdout = None
        try:
            for index, argv in enumerate(segments):
                is_last = index == len(segments) - 1
                proc = subprocess.Popen(
                    argv,
                    stdin=previous_stdout,
                    stdout=subprocess.PIPE if not is_last else subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=self._safe_env(),
                )
                if previous_stdout is not None:
                    previous_stdout.close()
                processes.append(proc)
                if not is_last:
                    previous_stdout = proc.stdout

            last = processes[-1]
            stdout, stderr = last.communicate(timeout=self.timeout)
            for proc in processes[:-1]:
                proc.wait(timeout=self.timeout)
            exit_status = last.returncode
            return exit_status, stdout or "", stderr or ""
        finally:
            for proc in processes:
                if proc.poll() is None:
                    proc.kill()

    def _run_redirect(self, expr: RedirectCommand) -> tuple[int, str, str]:
        target = Path(expr.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if expr.op == ">" else "a" if expr.op == ">>" else "w"
        stream = target.open(mode, encoding="utf-8")
        try:
            if isinstance(expr.cmd, SingleCommand):
                completed = subprocess.run(
                    expr.cmd.argv,
                    cwd=expr.cmd.cwd,
                    stdout=stream if expr.op in {">", ">>"} else subprocess.PIPE,
                    stderr=stream if expr.op == "2>" else subprocess.PIPE,
                    text=True,
                    timeout=self.timeout,
                    env=self._safe_env(),
                )
                return completed.returncode, "", completed.stderr or ""
            code, out, err = self._execute(expr.cmd)
            if expr.op in {">", ">>"}:
                stream.write(out)
            else:
                stream.write(err)
            return code, "", ""
        finally:
            stream.close()

    def _limit_output(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.output_limit:
            return text, False
        truncated = text[: self.output_limit]
        return truncated + "\n...[output truncated]...", True

    @staticmethod
    def _safe_env() -> dict[str, str]:
        """Return a trimmed environment safe for subprocess execution."""
        allowed = {
            "path",
            "lang",
            "lc_all",
            "home",
            "user",
            "logname",
            "term",
            "tmp",
            "temp",
            # Windows essentials — PowerShell fails without these (error 8009001d).
            "systemroot",
            "windir",
            "userprofile",
            "appdata",
            "localappdata",
            "homedrive",
            "homepath",
            "username",
            "userdomain",
            "computername",
            "comspec",
            "pathext",
            "psmodulepath",
            "programdata",
            "programfiles",
            "programfiles(x86)",
            "programw6432",
            "commonprogramfiles",
            "commonprogramfiles(x86)",
            "commonprogramw6432",
            "systemdrive",
            "os",
            "number_of_processors",
            "processor_architecture",
            "processor_identifier",
            "processor_level",
            "processor_revision",
            "allusersprofile",
            "driverdata",
            "windir",
        }
        return {
            key: value
            for key, value in os.environ.items()
            if key.lower() in allowed
        }
