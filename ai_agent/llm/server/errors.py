from __future__ import annotations

from ai_agent.llm.http.model_errors import format_model_missing_message


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
        super().__init__(
            format_model_missing_message(
                model,
                engine_name,
                upstream,
                available=self.available,
            )
        )
