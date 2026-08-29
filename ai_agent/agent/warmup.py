from __future__ import annotations

import logging
import time

from ai_agent.agent.tools import TOOL_DEFINITIONS
from ai_agent.llm.base import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)

WARMUP_USER_MESSAGE = "Startup warmup. Reply with the single word: ready"


def warmup_llm(llm: LLMProvider, system_prompt: str) -> tuple[bool, str, float]:
    """Load the model with the agent system prompt and tool schema."""
    logger.info(
        "Warming up model with agent context (system prompt + %d tools)",
        len(TOOL_DEFINITIONS),
    )
    start = time.perf_counter()
    response = llm.chat(
        [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=WARMUP_USER_MESSAGE),
        ],
        tools=TOOL_DEFINITIONS,
    )
    duration = time.perf_counter() - start

    if response.error:
        logger.warning("Model warmup failed after %.1fs: %s", duration, response.error)
        return False, response.error, duration

    logger.info("Model warmup complete in %.1fs (loaded with agent context)", duration)
    return True, "ready", duration
