from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from ai_agent.llm.client.errors import ModelMissingError
from ai_agent.llm.client.types import (
    LLMHealthcheck,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LlmServerInfo,
    StreamChunk,
    ToolCall,
)
from ai_agent.llm.http.errors import LLMErrorKind
from ai_agent.llm.http.session import LlmHttpSession, LlmSessionError

logger = logging.getLogger(__name__)


class FacadeLlmClient(LLMProvider):
    """Client for the agent LLM server's canonical HTTP API.

    The agent always speaks this one protocol. Engine choice (Ollama, vLLM, …)
    is handled server-side.
    """

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
        self._engine_name = ""
        self._cached_info: LlmServerInfo | None = None

    @property
    def endpoint(self) -> str:
        return self.session.base_url

    @property
    def engine_name(self) -> str:
        info = self.server_info()
        return info.engine if info else self._engine_name

    @property
    def model_name(self) -> str:
        info = self.server_info()
        return info.model if info else self._model

    def close(self) -> None:
        self.session.close()

    def server_info(self) -> LlmServerInfo | None:
        if self._cached_info is not None:
            return self._cached_info
        try:
            payload = self.session.get_json("/api/info", timeout=5.0)
        except LlmSessionError:
            return None
        if not isinstance(payload, dict):
            return None
        engine = payload.get("engine")
        model = payload.get("model")
        if not isinstance(engine, str) or not isinstance(model, str):
            return None
        upstream = payload.get("upstream")
        self._cached_info = LlmServerInfo(
            engine=engine,
            model=model,
            upstream=upstream if isinstance(upstream, str) else "",
        )
        self._engine_name = engine
        return self._cached_info

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        response: LLMResponse | None = None
        error: str | None = None
        error_kind: LLMErrorKind | None = None
        for chunk in self.chat_stream(messages, tools):
            if chunk.error:
                error = chunk.error
                error_kind = chunk.error_kind
            if chunk.response is not None:
                response = chunk.response
        if response is not None:
            if error and not response.error:
                response = LLMResponse(
                    message=response.message,
                    done=response.done,
                    model=response.model,
                    error=error,
                    error_kind=error_kind,
                    stop_reason=response.stop_reason,
                )
            return response
        return LLMResponse(
            message=LLMMessage(role="assistant", content=""),
            error=error or "LLM returned no response.",
            error_kind=error_kind or LLMErrorKind.EMPTY,
        )

    def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> Iterator[StreamChunk]:
        payload = {
            "model": self._model,
            "messages": [self._serialize_message(message) for message in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        options = self._options()
        if options:
            payload["options"] = options

        accumulator = _StreamAccumulator()
        model: str | None = None

        try:
            with self.session.stream_post("/api/chat", payload) as response:
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        error = "Malformed JSON chunk from LLM."
                        yield StreamChunk(
                            error=error,
                            error_kind=LLMErrorKind.PROTOCOL,
                            done=True,
                            response=LLMResponse(
                                message=LLMMessage(role="assistant", content=""),
                                error=error,
                                error_kind=LLMErrorKind.PROTOCOL,
                            ),
                        )
                        return

                    model = data.get("model", model)
                    message = data.get("message") or {}
                    content_delta = message.get("content") or None
                    if content_delta:
                        accumulator.content += content_delta

                    for chunk in accumulator.feed_tool_calls(
                        message.get("tool_calls") or []
                    ):
                        yield chunk

                    if content_delta:
                        yield StreamChunk(content_delta=content_delta)

                    if data.get("done"):
                        llm_response = accumulator.build_response(
                            model=model,
                            stop_reason=data.get("done_reason"),
                        )
                        yield StreamChunk(done=True, response=llm_response)
                        return

            if accumulator.has_content():
                error = "LLM stream ended before completion."
                llm_response = accumulator.build_response(
                    model=model,
                    error=error,
                    error_kind=LLMErrorKind.STREAM_INCOMPLETE,
                )
                yield StreamChunk(
                    done=True,
                    response=llm_response,
                    error=error,
                    error_kind=LLMErrorKind.STREAM_INCOMPLETE,
                )
                return

            error = "LLM stream ended with no data."
            yield StreamChunk(
                done=True,
                response=LLMResponse(
                    message=LLMMessage(role="assistant", content=""),
                    error=error,
                    error_kind=LLMErrorKind.EMPTY,
                ),
                error=error,
                error_kind=LLMErrorKind.EMPTY,
            )
        except LlmSessionError as exc:
            if exc.kind == LLMErrorKind.STREAM_INTERRUPTED:
                logger.warning("LLM stream interrupted: %s", exc)
            yield self._error_chunk(exc.message, exc.kind, accumulator, model)

    def healthcheck(self) -> LLMHealthcheck:
        info = self.server_info()
        engine_label = info.engine if info else "LLM server"

        try:
            payload = self.session.get_json("/api/tags", timeout=5.0)
        except LlmSessionError as exc:
            return LLMHealthcheck(ok=False, message=exc.message, error_kind=exc.kind)

        if not isinstance(payload, dict):
            return LLMHealthcheck(
                ok=False,
                message="LLM healthcheck returned an unexpected payload.",
                error_kind=LLMErrorKind.PROTOCOL,
            )

        models = payload.get("models", [])
        names = [
            item.get("name")
            for item in models
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
        configured_model = info.model if info else self._model
        if configured_model not in names and not any(
            name.startswith(f"{configured_model}:") for name in names
        ):
            missing = ModelMissingError(
                configured_model,
                engine_label,
                self.endpoint,
                available=names,
            )
            return LLMHealthcheck(
                ok=False,
                message=str(missing),
                error_kind=LLMErrorKind.MODEL_NOT_FOUND,
            )
        return LLMHealthcheck(ok=True, message="ok")

    def _error_chunk(
        self,
        error: str,
        error_kind: LLMErrorKind,
        accumulator: _StreamAccumulator,
        model: str | None,
    ) -> StreamChunk:
        if accumulator.has_content():
            response = accumulator.build_response(
                model=model,
                error=error,
                error_kind=error_kind,
            )
        else:
            response = LLMResponse(
                message=LLMMessage(role="assistant", content=""),
                error=error,
                error_kind=error_kind,
            )
        return StreamChunk(
            done=True,
            response=response,
            error=error,
            error_kind=error_kind,
        )

    def _options(self) -> dict:
        options: dict = {}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        return options

    @staticmethod
    def _serialize_message(message: LLMMessage) -> dict:
        payload: dict = {
            "role": message.role,
            "content": message.content,
        }
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        if message.name:
            payload["name"] = message.name
        return payload


class _ToolCallAccumulator:
    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments = ""

    def feed(self, item: dict) -> list[StreamChunk]:
        chunks: list[StreamChunk] = []
        function = item.get("function") or {}
        if function.get("name"):
            self.name = function["name"]
        if item.get("id"):
            self.id = item["id"]

        raw_args = function.get("arguments")
        if isinstance(raw_args, str) and raw_args:
            if self.arguments and raw_args.startswith(self.arguments):
                delta = raw_args[len(self.arguments) :]
                self.arguments = raw_args
            else:
                delta = raw_args
                self.arguments += raw_args
            if delta:
                chunks.append(
                    StreamChunk(
                        tool_name=self.name or None,
                        tool_arguments_delta=delta,
                    )
                )
        elif isinstance(raw_args, dict) and raw_args:
            encoded = json.dumps(raw_args, ensure_ascii=True, separators=(",", ":"))
            if encoded == self.arguments:
                return chunks
            if self.arguments and encoded.startswith(self.arguments):
                delta = encoded[len(self.arguments) :]
                self.arguments = encoded
            elif not self.arguments:
                delta = encoded
                self.arguments = encoded
            else:
                return chunks
            if delta:
                chunks.append(
                    StreamChunk(
                        tool_name=self.name or None,
                        tool_arguments_delta=delta,
                    )
                )
        return chunks

    def to_tool_call(self) -> ToolCall:
        raw_args = self.arguments
        if raw_args:
            try:
                parsed_args = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed_args = {"_malformed": raw_args}
        else:
            parsed_args = {}
        return ToolCall(
            id=self.id or self.name or "tool",
            name=self.name,
            arguments=parsed_args or {},
        )


class _StreamAccumulator:
    def __init__(self) -> None:
        self.content = ""
        self._tool_calls: list[_ToolCallAccumulator] = []

    def has_content(self) -> bool:
        return bool(self.content or self._tool_calls)

    def feed_tool_calls(self, tool_calls: list[dict]) -> list[StreamChunk]:
        chunks: list[StreamChunk] = []
        for index, item in enumerate(tool_calls):
            while len(self._tool_calls) <= index:
                self._tool_calls.append(_ToolCallAccumulator())
            chunks.extend(self._tool_calls[index].feed(item))
        return chunks

    def build_response(
        self,
        *,
        model: str | None = None,
        error: str | None = None,
        error_kind: LLMErrorKind | None = None,
        stop_reason: str | None = None,
    ) -> LLMResponse:
        tool_calls = [item.to_tool_call() for item in self._tool_calls]
        return LLMResponse(
            message=LLMMessage(
                role="assistant",
                content=self.content,
                tool_calls=tool_calls,
            ),
            done=True,
            model=model,
            error=error,
            error_kind=error_kind,
            stop_reason=stop_reason,
        )
