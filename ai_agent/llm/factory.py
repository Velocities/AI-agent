"""Backward-compatible re-exports. Prefer ai_agent.llm.client.factory."""

from __future__ import annotations

from ai_agent.config import LlmTransport, Settings
from ai_agent.llm.client.factory import create_http_session, create_llm_provider
from ai_agent.llm.client.types import LLMProvider


def create_upstream_provider(settings: Settings) -> LLMProvider:
    """Talk to real upstream inference, or to the far side of the SSH tunnel."""
    if settings.llm_engine.value == "ollama" and settings.llm_transport == LlmTransport.SSH:
        return create_llm_provider(settings)
    return create_llm_provider(settings, base_url=settings.llm_upstream)


__all__ = [
    "create_http_session",
    "create_llm_provider",
    "create_upstream_provider",
]
