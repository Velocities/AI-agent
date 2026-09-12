"""Backward-compatible alias. Prefer ai_agent.llm.client.provider.FacadeLlmClient."""

from ai_agent.llm.client.provider import FacadeLlmClient as OllamaProvider

__all__ = ["OllamaProvider"]
