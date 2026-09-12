from __future__ import annotations

from ai_agent.config import LlmTransport, Settings
from ai_agent.llm.client.provider import FacadeLlmClient
from ai_agent.llm.client.types import LLMProvider
from ai_agent.llm.http.session import LlmHttpSession
from ai_agent.llm.ssh_tunnel import start_ssh_tunnel


def create_http_session(settings: Settings, *, base_url: str | None = None) -> LlmHttpSession:
    if base_url is None and settings.llm_transport == LlmTransport.SSH:
        tunnel = start_ssh_tunnel(settings)
        return LlmHttpSession(
            tunnel.local_url,
            timeout=settings.llm_timeout,
            before_request=tunnel.ensure,
            on_close=tunnel.close,
        )
    return LlmHttpSession(
        base_url or settings.llm_host,
        timeout=settings.llm_timeout,
    )


def create_llm_provider(
    settings: Settings,
    *,
    base_url: str | None = None,
    session: LlmHttpSession | None = None,
) -> LLMProvider:
    """Build the agent-side LLM client. Callers should not import implementations."""
    http_session = session or create_http_session(settings, base_url=base_url)
    return FacadeLlmClient(
        http_session,
        model=settings.llm_model,
        num_predict=settings.ollama_num_predict,
        num_ctx=settings.ollama_num_ctx,
    )
