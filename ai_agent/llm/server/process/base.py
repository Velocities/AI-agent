from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from ai_agent.config import Settings
from ai_agent.llm.server.process.probe import wait_for_upstream

logger = logging.getLogger(__name__)


class EngineProcessError(RuntimeError):
    """Failed to start or reach an inference engine process."""


class EngineProcess(ABC):
    """Manages a local inference engine subprocess when needed."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._started_by_us = False

    @property
    @abstractmethod
    def engine_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def upstream_url(self) -> str:
        raise NotImplementedError

    @property
    def started_by_us(self) -> bool:
        return self._started_by_us

    @abstractmethod
    def _ready_path(self) -> str:
        raise NotImplementedError

    def ensure_running(self, *, timeout: float) -> None:
        if wait_for_upstream(self.upstream_url, self._ready_path(), timeout=1.0):
            logger.info("%s already reachable at %s", self.engine_name, self.upstream_url)
            self._started_by_us = False
            return
        self._start()
        self._started_by_us = True
        if not wait_for_upstream(
            self.upstream_url,
            self._ready_path(),
            timeout=timeout,
        ):
            self.stop()
            raise EngineProcessError(
                f"{self.engine_name} did not become ready at {self.upstream_url} "
                f"within {timeout:.0f}s."
            )

    @abstractmethod
    def _start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        if not self._started_by_us:
            return
        self._stop()
        self._started_by_us = False

    @abstractmethod
    def _stop(self) -> None:
        raise NotImplementedError


class ExternalEngineProcess(EngineProcess):
    """Use an upstream that ai-agent-llm does not manage (remote or pre-started)."""

    def __init__(self, settings: Settings, *, reason: str):
        super().__init__(settings)
        self._reason = reason

    @property
    def engine_name(self) -> str:
        return self.settings.llm_engine.value

    @property
    def upstream_url(self) -> str:
        return self.settings.llm_upstream

    def _ready_path(self) -> str:
        if self.settings.llm_engine.value == "vllm":
            return "/v1/models"
        return "/api/tags"

    def ensure_running(self, *, timeout: float) -> None:
        if wait_for_upstream(
            self.upstream_url,
            self._ready_path(),
            timeout=timeout,
        ):
            self._started_by_us = False
            return
        raise EngineProcessError(
            f"{self.engine_name} is not reachable at {self.upstream_url}. "
            f"{self._reason}"
        )

    def _start(self) -> None:
        raise EngineProcessError("External engine process cannot be started locally.")

    def _stop(self) -> None:
        return None
