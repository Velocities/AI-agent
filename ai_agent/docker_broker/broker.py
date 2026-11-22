"""In-process broker. The socket server and the tests both use this class.

``handle`` is the whole protocol. Callers send an intent. The broker builds
the Docker argv itself, refuses anything else, and only then calls ``runner``.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

from ai_agent.docker_broker.authorize import BrokerRejected, authorize, plan_target_exec
from ai_agent.workflows.container import SLEEP_ROOT

logger = logging.getLogger(__name__)

Runner = Callable[..., subprocess.CompletedProcess[str]]

_EXEC_FIELDS = {
    "op",
    "container",
    "user",
    "cwd",
    "argv",
    "script",
    "script_args",
    "stdin",
    "timeout",
}
_INVOKE_FIELDS = {"op", "argv", "stdin", "timeout"}
_MAX_TIMEOUT = {
    "exec": 600.0,
    "invoke": 30 * 60.0,
}


class DockerBroker:
    def __init__(
        self,
        runner: Runner,
        *,
        workflow_image_root: Path | None = None,
        sleep_root: Path = SLEEP_ROOT,
        run_guard: Callable[[], str | None] | None = None,
    ) -> None:
        self._runner = runner
        self.workflow_image_root = workflow_image_root
        self.sleep_root = sleep_root
        self._run_guard = run_guard

    def exec(
        self,
        *,
        container: str,
        user: str = "",
        cwd: str | None = None,
        argv: list[str] | None = None,
        script: str | None = None,
        script_args: list[str] | None = None,
        stdin: str | None = None,
        timeout: float = 120,
    ) -> subprocess.CompletedProcess[str]:
        return self.handle(
            {
                "op": "exec",
                "container": container,
                "user": user,
                "cwd": cwd,
                "argv": argv,
                "script": script,
                "script_args": script_args,
                "stdin": stdin,
                "timeout": timeout,
            }
        )

    def invoke(
        self,
        argv: list[str],
        *,
        timeout: float,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run argv the caller already built, after :func:`authorize` accepts it."""
        return self.handle(
            {"op": "invoke", "argv": argv, "stdin": stdin, "timeout": timeout}
        )

    def handle(self, message: dict) -> subprocess.CompletedProcess[str]:
        op = message.get("op") if isinstance(message, dict) else None
        try:
            if not isinstance(message, dict):
                raise BrokerRejected("Broker requests are objects.")
            if op == "exec":
                self._only(_EXEC_FIELDS, message)
                user = message.get("user", "")
                if user is None:
                    user = ""
                planned = plan_target_exec(
                    container=message.get("container", ""),
                    user=user,
                    cwd=message.get("cwd"),
                    argv=message.get("argv"),
                    script=message.get("script"),
                    script_args=message.get("script_args"),
                )
                authorize(planned)
            elif op == "invoke":
                self._only(_INVOKE_FIELDS, message)
                planned = authorize(
                    message.get("argv"),
                    workflow_image_root=self.workflow_image_root,
                    sleep_root=self.sleep_root,
                )
                if planned[1] == "run" and self._run_guard is not None:
                    problem = self._run_guard()
                    if problem:
                        raise BrokerRejected(problem)
            else:
                raise BrokerRejected(
                    f"Unknown broker operation {op!r}. Use exec or invoke."
                )
            timeout = _bounded_timeout(message.get("timeout"), limit=_MAX_TIMEOUT[op])
            stdin = message.get("stdin")
            if stdin is not None and (
                not isinstance(stdin, str) or len(stdin) > 1_000_000
            ):
                raise BrokerRejected("stdin must be text of at most 1 MB.")
            logger.info(
                "Docker broker running %s",
                planned[1] if len(planned) > 1 else "docker",
            )
            result = self._runner(planned, timeout=timeout, stdin=stdin)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                logger.warning(
                    "Docker broker command failed (exit %s, op=%s): %s",
                    result.returncode,
                    op,
                    detail[:2000] if detail else "(no output)",
                )
            return result
        except BrokerRejected as exc:
            logger.warning(
                "Docker broker refused op=%s: %s; request=%s",
                op,
                exc,
                _request_summary(message),
            )
            raise

    @staticmethod
    def _only(allowed: set[str], message: dict) -> None:
        extra = set(message) - allowed
        if extra:
            raise BrokerRejected(
                "Unknown broker fields: " + ", ".join(sorted(extra))
            )


def _request_summary(message: object) -> str:
    if not isinstance(message, dict):
        return repr(message)
    op = message.get("op")
    if op == "invoke":
        argv = message.get("argv")
        if isinstance(argv, list):
            return _argv_preview(argv)
    if op == "exec":
        container = message.get("container", "")
        argv = message.get("argv")
        if isinstance(argv, list) and argv:
            return f"container={container!r} argv={_argv_preview(argv)}"
        if message.get("script"):
            return f"container={container!r} script=<{len(str(message.get('script')))} chars>"
    return f"op={op!r}"


def _argv_preview(argv: list[str], *, limit: int = 8) -> str:
    head = argv[:limit]
    text = " ".join(head)
    if len(argv) > limit:
        text += " …"
    return text


def _bounded_timeout(value: object, *, limit: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrokerRejected("timeout must be a number of seconds.")
    if value <= 0:
        raise BrokerRejected("timeout must be positive.")
    return min(float(value), limit)
