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
    # Descriptive fields from the engine show document. Never inferred from the name.
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    context_length: int | None = None


def probe_model_info(engine, settings: Settings, *, warmup_ok: bool) -> ModelInfo:
    model = getattr(engine, "model", None) or settings.llm_model
    upstream = getattr(engine, "upstream_url", None) or settings.llm_upstream
    if settings.llm_engine == LlmEngineKind.OLLAMA:
        show = _ollama_show(engine)
        capabilities = _capabilities_from_show(show)
        family, parameter_size, quantization, context_length = _description_from_show(show)
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
            family=family,
            parameter_size=parameter_size,
            quantization=quantization,
            context_length=context_length,
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


def _ollama_show(engine) -> dict:
    show = getattr(engine, "show_model", None)
    if not callable(show):
        return {}
    try:
        payload = show()
    except Exception:
        logger.warning("Ollama capability probe failed", exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def _capabilities_from_show(payload: dict) -> frozenset[str]:
    raw = payload.get("capabilities")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(item for item in raw if isinstance(item, str))


def _description_from_show(payload: dict) -> tuple[str | None, str | None, str | None, int | None]:
    """Family, parameter size, quantization, and context length from `/api/show`."""
    details = payload.get("details")
    family = parameter_size = quantization = None
    if isinstance(details, dict):
        family = _text(details.get("family"))
        parameter_size = _text(details.get("parameter_size"))
        quantization = _text(details.get("quantization_level"))
    return family, parameter_size, quantization, _context_length(payload.get("model_info"))


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _context_length(model_info: object) -> int | None:
    if not isinstance(model_info, dict):
        return None
    lengths = [
        value
        for key, value in model_info.items()
        if isinstance(key, str)
        and key.endswith(".context_length")
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
    ]
    return max(lengths) if lengths else None
