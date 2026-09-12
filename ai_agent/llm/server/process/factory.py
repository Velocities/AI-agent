from __future__ import annotations

from ai_agent.config import LlmEngineKind, LlmTransport, Settings
from ai_agent.llm.server.process.base import EngineProcess, ExternalEngineProcess
from ai_agent.llm.server.process.ollama import OllamaEngineProcess
from ai_agent.llm.server.process.vllm import VLLMEngineProcess


def create_engine_process(settings: Settings) -> EngineProcess:
    if not settings.llm_manage_upstream:
        return ExternalEngineProcess(
            settings,
            reason="LLM_MANAGE_UPSTREAM is disabled.",
        )
    if settings.llm_transport == LlmTransport.SSH:
        return ExternalEngineProcess(
            settings,
            reason="SSH transport expects the engine on the remote host.",
        )
    if settings.llm_engine == LlmEngineKind.VLLM:
        return VLLMEngineProcess(settings)
    return OllamaEngineProcess(settings)
