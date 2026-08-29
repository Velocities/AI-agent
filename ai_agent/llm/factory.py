from __future__ import annotations

from ai_agent.config import Settings
from ai_agent.llm.base import LLMProvider
from ai_agent.llm.ollama import OllamaProvider
from ai_agent.llm.session import LlmHttpSession


def create_http_session(settings: Settings, *, base_url: str | None = None) -> LlmHttpSession:
    return LlmHttpSession(
        base_url=base_url or settings.ollama_host,
        timeout=settings.ollama_timeout,
    )


def create_llm_provider(
    settings: Settings,
    *,
    base_url: str | None = None,
    session: LlmHttpSession | None = None,
) -> LLMProvider:
    """Build the configured LLM provider. Callers should not import implementations."""
    http_session = session or create_http_session(settings, base_url=base_url)
    return OllamaProvider(
        http_session,
        model=settings.ollama_model,
        num_predict=settings.ollama_num_predict,
        num_ctx=settings.ollama_num_ctx,
    )


def create_upstream_provider(settings: Settings) -> LLMProvider:
    """Provider that talks to real Ollama, not the local ai-agent-llm facade."""
    return create_llm_provider(settings, base_url=settings.ollama_upstream)
