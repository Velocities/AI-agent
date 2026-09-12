from __future__ import annotations

import importlib.util
import shutil
import sys

from ai_agent.config import Settings
from ai_agent.llm.server.process.base import EngineProcessError
from ai_agent.llm.server.process.subprocess_base import (
    SubprocessEngineProcess,
    upstream_host_port,
)


class VLLMEngineProcess(SubprocessEngineProcess):
    DISPLAY_NAME = "vLLM"

    def __init__(self, settings: Settings):
        super().__init__(
            settings,
            binary_name="vllm",
            binary_override=settings.llm_vllm_binary,
        )

    @property
    def engine_name(self) -> str:
        return self.DISPLAY_NAME

    def _ready_path(self) -> str:
        return "/v1/models"

    def _command(self) -> list[str]:
        host, port = upstream_host_port(self.settings)
        serve_args = [
            "serve",
            self.settings.llm_model,
            "--host",
            host,
            "--port",
            str(port),
        ]
        if self._binary_override:
            return [self._binary_override, *serve_args]
        if path := shutil.which("vllm"):
            return [path, *serve_args]
        if importlib.util.find_spec("vllm") is not None:
            return [sys.executable, "-m", "vllm", *serve_args]
        raise EngineProcessError(_vllm_missing_message())


def _vllm_missing_message() -> str:
    if sys.platform == "win32":
        platform_hint = (
            "vLLM is not installed in this Python environment, and it does not "
            "officially support native Windows. Options: (1) use LLM_ENGINE=ollama "
            "on Windows, (2) run vLLM in WSL2/Linux and point LLM_UPSTREAM at it "
            "with LLM_MANAGE_UPSTREAM=false, or (3) install a community Windows "
            "vLLM build and set LLM_VLLM_BINARY to its executable."
        )
    else:
        platform_hint = (
            "Install vLLM in this environment with: pip install vllm "
            "(requires Linux + NVIDIA CUDA for GPU inference)."
        )
    return (
        "Could not find vLLM. "
        f"{platform_hint} "
        "See https://docs.vllm.ai/en/latest/getting_started/installation/ "
        "and ai_agent/llm/ARCHITECTURE.md."
    )
