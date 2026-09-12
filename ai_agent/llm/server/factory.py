from __future__ import annotations

from ai_agent.config import LlmEngineKind, LlmTransport, Settings
from ai_agent.llm.http.session import LlmHttpSession
from ai_agent.llm.server.engine.base import LlmEngine
from ai_agent.llm.server.engine.ollama import OllamaEngine
from ai_agent.llm.server.engine.vllm import VLLMEngine
from ai_agent.llm.ssh_tunnel import start_ssh_tunnel


def create_upstream_session(
    settings: Settings,
    *,
    base_url: str | None = None,
) -> LlmHttpSession:
    if base_url is not None:
        return LlmHttpSession(base_url, timeout=settings.llm_timeout)
    if settings.llm_engine == LlmEngineKind.OLLAMA and settings.ollama_transport == LlmTransport.SSH:
        tunnel = start_ssh_tunnel(settings)
        return LlmHttpSession(
            tunnel.local_url,
            timeout=settings.llm_timeout,
            before_request=tunnel.ensure,
            on_close=tunnel.close,
        )
    return LlmHttpSession(settings.llm_upstream_url(), timeout=settings.llm_timeout)


def create_engine(
    settings: Settings,
    *,
    session: LlmHttpSession | None = None,
) -> LlmEngine:
    """Build the configured server-side inference engine."""
    upstream = session or create_upstream_session(settings)
    if settings.llm_engine == LlmEngineKind.VLLM:
        return VLLMEngine(
            upstream,
            model=settings.llm_model,
            max_tokens=settings.vllm_max_tokens,
        )
    return OllamaEngine(
        upstream,
        model=settings.llm_model,
        num_predict=settings.llm_num_predict,
        num_ctx=settings.llm_num_ctx,
    )
