from __future__ import annotations

from ai_agent.config import Settings
from ai_agent.llm.base import LLMProvider
from ai_agent.llm.ollama import OllamaProvider
from ai_agent.llm.session import LlmHttpSession


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Build the configured LLM provider. Callers should not import implementations."""
    session = LlmHttpSession(
        base_url=settings.ollama_host,
        timeout=settings.ollama_timeout,
    )
    return OllamaProvider(
        session,
        model=settings.ollama_model,
        num_predict=settings.ollama_num_predict,
        num_ctx=settings.ollama_num_ctx,
    )
