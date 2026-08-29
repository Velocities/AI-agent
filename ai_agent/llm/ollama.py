from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx

from ai_agent.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    StreamChunk,
    ToolCall,
)

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        host: str,
        model: str,
        timeout: float = 600.0,
        num_predict: int | None = None,
        num_ctx: int | None = None,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_predict = num_predict
        self.num_ctx = num_ctx

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        response: LLMResponse | None = None
        error: str | None = None
        for chunk in self.chat_stream(messages, tools):
            if chunk.error:
                error = chunk.error
            if chunk.response is not None:
                response = chunk.response
        if response is not None:
            if error and not response.error:
                response = LLMResponse(
                    message=response.message,
                    done=response.done,
                    model=response.model,
                    error=error,
                )
            return response
        return LLMResponse(
            message=LLMMessage(role="assistant", content=""),
            error=error or "Ollama returned no response.",
        )

    def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> Iterator[StreamChunk]:
        payload = {
            "model": self.model,
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
        timeout = httpx.Timeout(
            connect=10.0,
            read=self.timeout,
            write=10.0,
            pool=10.0,
        )

        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.host}/api/chat",
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            yield StreamChunk(
                                error="Malformed JSON chunk from Ollama.",
                                done=True,
                                response=LLMResponse(
                                    message=LLMMessage(role="assistant", content=""),
                                    error="Malformed JSON chunk from Ollama.",
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
                llm_response = accumulator.build_response(model=model)
                yield StreamChunk(
                    done=True,
                    response=llm_response,
                    error="Ollama stream ended before completion.",
                )
                return

            yield StreamChunk(
                done=True,
                response=LLMResponse(
                    message=LLMMessage(role="assistant", content=""),
                    error="Ollama stream ended with no data.",
                ),
                error="Ollama stream ended with no data.",
            )
        except httpx.ConnectError:
            error = "Ollama is unavailable. Check OLLAMA_HOST."
            yield self._error_chunk(error, accumulator, model)
        except httpx.HTTPStatusError as exc:
            error = f"Ollama HTTP error: {exc.response.status_code}"
            yield self._error_chunk(error, accumulator, model)
        except httpx.TimeoutException:
            error = "Ollama request timed out."
            yield self._error_chunk(error, accumulator, model)
        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.StreamError) as exc:
            logger.warning("Ollama stream interrupted: %s", exc)
            error = "Ollama stream was interrupted."
            yield self._error_chunk(error, accumulator, model)

    def _error_chunk(
        self,
        error: str,
        accumulator: _StreamAccumulator,
        model: str | None,
    ) -> StreamChunk:
        if accumulator.has_content():
            response = accumulator.build_response(model=model, error=error)
        else:
            response = LLMResponse(
                message=LLMMessage(role="assistant", content=""),
                error=error,
            )
        return StreamChunk(done=True, response=response, error=error)

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

    def healthcheck(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.host}/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
                names = {item.get("name") for item in models}
                if self.model not in names and not any(
                    name.startswith(f"{self.model}:") for name in names if name
                ):
                    return False, f"Model '{self.model}' not found in Ollama."
                return True, "ok"
        except httpx.HTTPError as exc:
            return False, f"Ollama healthcheck failed: {exc}"


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
            stop_reason=stop_reason,
        )
