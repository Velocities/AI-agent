from __future__ import annotations

import json
import logging
import time
from typing import Any

from ai_agent.agent.tools import TOOL_DEFINITIONS
from ai_agent.llm.server.engine.base import LlmEngine

logger = logging.getLogger(__name__)

WARMUP_USER_MESSAGE = "Startup warmup. Reply with the single word: ready"


def warmup_engine(
    engine: LlmEngine,
    system_prompt: str,
    tools: list | None = None,
) -> tuple[bool, str, float]:
    """Load the model with the agent system prompt and tool schema."""
    tool_defs = tools if tools is not None else TOOL_DEFINITIONS
    logger.info(
        "Warming up %s model %s (system prompt + %d tools)",
        engine.engine_name,
        engine.model,
        len(tool_defs),
    )
    payload: dict[str, Any] = {
        "model": engine.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": WARMUP_USER_MESSAGE},
        ],
        "stream": True,
        "tools": tool_defs,
    }
    start = time.perf_counter()
    content = ""
    try:
        for line in engine.chat_lines(payload):
            data = json.loads(line)
            message = data.get("message") or {}
            if message.get("content"):
                content += message["content"]
    except Exception as exc:
        duration = time.perf_counter() - start
        detail = str(exc)
        logger.warning("Model warmup failed after %.1fs: %s", duration, detail)
        return False, detail, duration

    duration = time.perf_counter() - start
    if not content.strip():
        detail = "LLM warmup returned no content."
        logger.warning("Model warmup failed after %.1fs: %s", duration, detail)
        return False, detail, duration

    logger.info("Model warmup complete in %.1fs (loaded with agent context)", duration)
    return True, "ready", duration
