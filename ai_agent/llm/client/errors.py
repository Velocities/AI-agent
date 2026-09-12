from __future__ import annotations

from ai_agent.llm.http.model_errors import format_model_missing_message


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
        super().__init__(
            format_model_missing_message(
                model,
                engine_name,
                endpoint,
                available=self.available,
            )
        )
