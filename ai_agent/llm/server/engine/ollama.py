from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ai_agent.llm.http.errors import LLMErrorKind
from ai_agent.llm.http.session import LlmHttpSession, LlmSessionError
from ai_agent.llm.server.engine.base import EngineHealth, LlmEngine
from ai_agent.llm.server.errors import EngineModelMissingError


class OllamaEngine(LlmEngine):
    """Engine that talks to a native Ollama HTTP API."""

    DISPLAY_NAME = "Ollama"

    def __init__(
        self,
        session: LlmHttpSession,
        model: str,
        *,
        num_predict: int | None = None,
        num_ctx: int | None = None,
    ):
        self.session = session
        self._model = model
        self.num_predict = num_predict
        self.num_ctx = num_ctx

    @property
    def engine_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def model(self) -> str:
        return self._model

    @property
    def upstream_url(self) -> str:
        return self.session.base_url

    def close(self) -> None:
        self.session.close()

    def list_models(self) -> dict[str, Any]:
        payload = self.session.get_json("/api/tags", timeout=5.0)
        if not isinstance(payload, dict):
            raise LlmSessionError(
                LLMErrorKind.PROTOCOL,
                "Ollama /api/tags returned an unexpected payload.",
            )
        return payload

    def chat_lines(self, payload: dict[str, Any]) -> Iterator[str]:
        upstream_payload = dict(payload)
        upstream_payload.setdefault("model", self._model)
        options = self._options()
        if options:
            merged = dict(upstream_payload.get("options") or {})
            merged.update(options)
            upstream_payload["options"] = merged
        with self.session.stream_post("/api/chat", upstream_payload) as response:
            for line in response.iter_lines():
                if line:
                    yield line

    def healthcheck(self) -> EngineHealth:
        try:
            payload = self.list_models()
        except LlmSessionError as exc:
            return EngineHealth(ok=False, message=exc.message)

        models = payload.get("models", [])
        names = [
            item.get("name")
            for item in models
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
        if self._model not in names and not any(
            name.startswith(f"{self._model}:") for name in names
        ):
            missing = EngineModelMissingError(
                self._model,
                self.engine_name,
                self.upstream_url,
                available=names,
            )
            return EngineHealth(ok=False, message=str(missing))
        return EngineHealth(ok=True, message="ok")

    def _options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        return options
