from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from abc import abstractmethod

from ai_agent.llm.server.process.base import EngineProcess, EngineProcessError
from ai_agent.llm.server.process.url import normalize_upstream_url, parse_upstream_url

logger = logging.getLogger(__name__)


class SubprocessEngineProcess(EngineProcess):
    def __init__(self, settings, *, binary_name: str, binary_override: str | None):
        super().__init__(settings)
        self._binary_name = binary_name
        self._binary_override = binary_override
        self._binary: str | None = None
        self._process: subprocess.Popen[str] | None = None
        self._upstream = normalize_upstream_url(settings.llm_upstream)

    @property
    def upstream_url(self) -> str:
        return self._upstream

    @abstractmethod
    def _command(self) -> list[str]:
        raise NotImplementedError

    def _subprocess_env(self) -> dict[str, str]:
        return os.environ.copy()

    def _binary_path(self) -> str:
        if self._binary is None:
            self._binary = _resolve_binary(self._binary_name, self._binary_override)
        return self._binary

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        command = self._command()
        logger.info("Starting %s: %s", self.engine_name, " ".join(command))
        kwargs: dict = {
            "env": self._subprocess_env(),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            self._process = subprocess.Popen(command, **kwargs)
        except OSError as exc:
            raise EngineProcessError(
                f"Failed to launch {self.engine_name} using {command[0]!r}: {exc}"
            ) from exc

    def _stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is not None:
            self._process = None
            return
        logger.info("Stopping %s (pid %s)", self.engine_name, process.pid)
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                check=False,
                capture_output=True,
                text=True,
            )
        else:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stderr is not None:
            stderr = process.stderr.read()
            if stderr.strip():
                logger.debug("%s stderr: %s", self.engine_name, stderr.strip())
        self._process = None


def _resolve_binary(name: str, override: str | None) -> str:
    if override:
        return override
    path = shutil.which(name)
    if path:
        return path
    raise EngineProcessError(
        f"{name!r} was not found on PATH. Install it or set the engine-specific "
        f"binary override in your environment."
    )


def upstream_host_port(settings) -> tuple[str, int]:
    return parse_upstream_url(normalize_upstream_url(settings.llm_upstream))
