"""Startup snapshot of what the running model can do.

Vision and tools come from the engine probe or from warmup. They are never
inferred from the model name.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ai_agent.config import LlmEngineKind, Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    engine: str
    model: str
    upstream: str
    capabilities: frozenset[str]
    vision: bool
    tools: bool
    vision_source: str  # "probed" | "configured"
    tools_source: str  # "probed" | "warmup"
    vision_verified: bool
    tools_verified: bool


def probe_model_info(engine, settings: Settings, *, warmup_ok: bool) -> ModelInfo:
    model = getattr(engine, "model", None) or settings.llm_model
    upstream = getattr(engine, "upstream_url", None) or settings.llm_upstream
    if settings.llm_engine == LlmEngineKind.OLLAMA:
        capabilities = _ollama_capabilities(engine)
        vision = "vision" in capabilities
        tools = "tools" in capabilities
        return ModelInfo(
            engine=settings.llm_engine.value,
            model=str(model),
            upstream=str(upstream),
            capabilities=capabilities,
            vision=vision,
            tools=tools,
            vision_source="probed",
            tools_source="probed",
            vision_verified=vision,
            tools_verified=tools,
        )
    capabilities = {"completion", "tools"}
    if settings.llm_vision:
        capabilities.add("vision")
    return ModelInfo(
        engine=settings.llm_engine.value,
        model=str(model),
        upstream=str(upstream),
        capabilities=frozenset(capabilities),
        vision=bool(settings.llm_vision),
        tools=bool(warmup_ok),
        vision_source="configured",
        tools_source="warmup",
        vision_verified=False,
        tools_verified=bool(warmup_ok),
    )


def _ollama_capabilities(engine) -> frozenset[str]:
    show = getattr(engine, "show_model", None)
    if not callable(show):
        return frozenset()
    try:
        payload = show()
    except Exception:
        logger.warning("Ollama capability probe failed", exc_info=True)
        return frozenset()
    if not isinstance(payload, dict):
        return frozenset()
    raw = payload.get("capabilities")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(item for item in raw if isinstance(item, str))
