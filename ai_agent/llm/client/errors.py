from __future__ import annotations


class ModelMissingError(Exception):
    """Raised when the configured model is not available on the connected server."""

    def __init__(
        self,
        model: str,
        engine_name: str,
        endpoint: str,
        *,
        available: list[str] | None = None,
    ):
        self.model = model
        self.engine_name = engine_name
        self.endpoint = endpoint
        self.available = available or []
        detail = (
            f"ModelMissingError: the requested model '{model}' was not available "
            f"for {engine_name} at {endpoint}."
        )
        if self.available:
            detail += f" Available models: {', '.join(self.available)}."
        super().__init__(detail)
