from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ai_agent.llm.http.errors import LLMErrorKind
from ai_agent.llm.http.session import LlmHttpSession, LlmSessionError
from ai_agent.llm.server.engine.base import EngineHealth, LlmEngine
from ai_agent.llm.server.errors import EngineModelMissingError
from ai_agent.llm.server.protocol import chat_chunk_line, tags_payload


class VLLMEngine(LlmEngine):
    """Engine that talks to a vLLM OpenAI-compatible API and emits canonical chat lines."""

    DISPLAY_NAME = "vLLM"

    def __init__(
        self,
        session: LlmHttpSession,
        model: str,
        *,
        max_tokens: int | None = None,
    ):
        self.session = session
        self._model = model
        self.max_tokens = max_tokens

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
        payload = self.session.get_json("/v1/models", timeout=5.0)
        if not isinstance(payload, dict):
            raise LlmSessionError(
                LLMErrorKind.PROTOCOL,
                "vLLM /v1/models returned an unexpected payload.",
            )
        data = payload.get("data", [])
        names = [
            item.get("id")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        return tags_payload(names)

    def chat_lines(self, payload: dict[str, Any]) -> Iterator[str]:
        openai_payload = self._to_openai_payload(payload)
        with self.session.stream_post("/v1/chat/completions", openai_payload) as response:
            yield from self._canonical_lines_from_sse(response.iter_lines())

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
        if self._model not in names:
            missing = EngineModelMissingError(
                self._model,
                self.engine_name,
                self.upstream_url,
                available=names,
            )
            return EngineHealth(ok=False, message=str(missing))
        return EngineHealth(ok=True, message="ok")

    def _to_openai_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = payload.get("model") or self._model
        messages = [
            self._to_openai_message(item)
            for item in payload.get("messages", [])
            if isinstance(item, dict)
        ]
        openai_payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if payload.get("tools"):
            openai_payload["tools"] = payload["tools"]
        options = payload.get("options") or {}
        max_tokens = options.get("num_predict", self.max_tokens)
        if max_tokens is not None:
            openai_payload["max_tokens"] = max_tokens
        return openai_payload

    @staticmethod
    def _to_openai_message(message: dict[str, Any]) -> dict[str, Any]:
        openai_message: dict[str, Any] = {
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
        }
        if message.get("tool_calls"):
            openai_message["tool_calls"] = [
                {
                    "id": call.get("id") or call.get("function", {}).get("name", "tool"),
                    "type": call.get("type", "function"),
                    "function": {
                        "name": call.get("function", {}).get("name", ""),
                        "arguments": json.dumps(
                            call.get("function", {}).get("arguments", {}),
                            ensure_ascii=True,
                            separators=(",", ":"),
                        ),
                    },
                }
                for call in message["tool_calls"]
                if isinstance(call, dict)
            ]
        if message.get("tool_call_id"):
            openai_message["tool_call_id"] = message["tool_call_id"]
        if message.get("name"):
            openai_message["name"] = message["name"]
        return openai_message

    def _canonical_lines_from_sse(self, lines: Iterator[str]) -> Iterator[str]:
        model = self._model
        content = ""
        tool_calls: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None

        for raw_line in lines:
            if not raw_line:
                continue
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                raise LlmSessionError(
                    LLMErrorKind.PROTOCOL,
                    "vLLM returned malformed SSE JSON.",
                ) from None

            if isinstance(chunk.get("model"), str):
                model = chunk["model"]

            for choice in chunk.get("choices", []):
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    continue
                if delta.get("content"):
                    content += delta["content"]
                    yield chat_chunk_line(
                        model=model,
                        message={"role": "assistant", "content": delta["content"]},
                    )
                for tool_delta in delta.get("tool_calls") or []:
                    if not isinstance(tool_delta, dict):
                        continue
                    index = int(tool_delta.get("index", 0))
                    slot = tool_calls.setdefault(
                        index,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    if tool_delta.get("id"):
                        slot["id"] = tool_delta["id"]
                    function = tool_delta.get("function") or {}
                    if function.get("name"):
                        slot["name"] = function["name"]
                    if function.get("arguments"):
                        slot["arguments"] += function["arguments"]
                    yield chat_chunk_line(
                        model=model,
                        message={
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": slot["name"],
                                        "arguments": slot["arguments"],
                                    }
                                }
                            ],
                        },
                    )
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])

        done_reason = _map_finish_reason(finish_reason)
        final_tool_calls = [
            {
                "id": slot["id"] or slot["name"] or "tool",
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": slot["arguments"],
                },
            }
            for _, slot in sorted(tool_calls.items())
            if slot["name"] or slot["arguments"]
        ]
        final_message: dict[str, Any] = {"role": "assistant", "content": ""}
        if final_tool_calls:
            final_message["tool_calls"] = final_tool_calls
        yield chat_chunk_line(
            model=model,
            message=final_message,
            done=True,
            done_reason=done_reason,
        )


def _map_finish_reason(finish_reason: str | None) -> str | None:
    if finish_reason is None:
        return None
    if finish_reason == "length":
        return "length"
    if finish_reason in {"stop", "tool_calls"}:
        return "stop"
    return finish_reason
