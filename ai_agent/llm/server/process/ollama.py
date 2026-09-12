from __future__ import annotations

from ai_agent.config import Settings
from ai_agent.llm.server.process.subprocess_base import (
    SubprocessEngineProcess,
    upstream_host_port,
)


class OllamaEngineProcess(SubprocessEngineProcess):
    DISPLAY_NAME = "Ollama"

    def __init__(self, settings: Settings):
        super().__init__(
            settings,
            binary_name="ollama",
            binary_override=settings.llm_ollama_binary,
        )

    @property
    def engine_name(self) -> str:
        return self.DISPLAY_NAME

    def _ready_path(self) -> str:
        return "/api/tags"

    def _command(self) -> list[str]:
        return [self._binary_path(), "serve"]

    def _subprocess_env(self) -> dict[str, str]:
        host, port = upstream_host_port(self.settings)
        env = super()._subprocess_env()
        env["OLLAMA_HOST"] = f"{host}:{port}"
        return env
