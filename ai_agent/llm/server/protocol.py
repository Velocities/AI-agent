from __future__ import annotations

import json
from typing import Any


def tags_payload(model_names: list[str]) -> dict[str, Any]:
    """Canonical /api/tags response shape exposed by the agent LLM facade."""
    return {"models": [{"name": name} for name in model_names]}


def info_payload(*, engine: str, model: str, upstream: str) -> dict[str, str]:
    """Canonical /api/info response shape exposed by the agent LLM facade."""
    return {"engine": engine, "model": model, "upstream": upstream}


def chat_chunk_line(
    *,
    model: str,
    message: dict[str, Any],
    done: bool = False,
    done_reason: str | None = None,
) -> str:
    """One NDJSON line in the canonical /api/chat stream."""
    payload: dict[str, Any] = {"model": model, "message": message, "done": done}
    if done_reason is not None:
        payload["done_reason"] = done_reason
    return json.dumps(payload, ensure_ascii=True)
