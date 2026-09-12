from __future__ import annotations


class EngineModelMissingError(Exception):
    """Raised when the configured model is not available on the upstream engine."""

    def __init__(
        self,
        model: str,
        engine_name: str,
        upstream: str,
        *,
        available: list[str] | None = None,
    ):
        self.model = model
        self.engine_name = engine_name
        self.upstream = upstream
        self.available = available or []
        detail = (
            f"ModelMissingError: the requested model '{model}' was not available "
            f"for {engine_name} at {upstream}."
        )
        if self.available:
            detail += f" Available models: {', '.join(self.available)}."
        super().__init__(detail)
