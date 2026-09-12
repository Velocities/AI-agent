from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EngineHealth:
    ok: bool
    message: str


class LlmEngine(ABC):
    """Server-side inference engine (Ollama, vLLM, …)."""

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Human-readable label shown to agent users."""

    @property
    @abstractmethod
    def model(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def upstream_url(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> dict[str, Any]:
        """Return canonical /api/tags payload."""

    @abstractmethod
    def chat_lines(self, payload: dict[str, Any]) -> Iterator[str]:
        """Yield canonical NDJSON /api/chat lines."""

    @abstractmethod
    def healthcheck(self) -> EngineHealth:
        raise NotImplementedError

    def close(self) -> None:
        return None
