from __future__ import annotations


def format_model_missing_message(
    model: str,
    engine_name: str,
    endpoint: str,
    *,
    available: list[str] | None = None,
) -> str:
    """User-facing message when LLM_MODEL is not served by the configured engine."""
    detail = (
        f"ModelMissingError: the requested model '{model}' is not available "
        f"with {engine_name} at {endpoint}."
    )
    names = [name for name in (available or []) if name]
    if names:
        detail += f" Available models: {', '.join(names)}."
    return detail
