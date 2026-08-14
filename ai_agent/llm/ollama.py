from __future__ import annotations

import json
import logging

import httpx

from ai_agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, host: str, model: str, timeout: float = 120.0):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [self._serialize_message(message) for message in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.host}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError:
            return LLMResponse(
                message=LLMMessage(role="assistant", content=""),
                error="Ollama is unavailable. Check OLLAMA_HOST.",
            )
        except httpx.HTTPStatusError as exc:
            return LLMResponse(
                message=LLMMessage(role="assistant", content=""),
                error=f"Ollama HTTP error: {exc.response.status_code}",
            )
        except httpx.TimeoutException:
            return LLMResponse(
                message=LLMMessage(role="assistant", content=""),
                error="Ollama request timed out.",
            )
        except json.JSONDecodeError:
            return LLMResponse(
                message=LLMMessage(role="assistant", content=""),
                error="Malformed JSON response from Ollama.",
            )

        message = data.get("message", {})
        tool_calls = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            raw_args = function.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    raw_args = {"_malformed": raw_args}
            tool_calls.append(
                ToolCall(
                    id=item.get("id") or function.get("name", "tool"),
                    name=function.get("name", ""),
                    arguments=raw_args or {},
                )
            )

        return LLMResponse(
            message=LLMMessage(
                role=message.get("role", "assistant"),
                content=message.get("content") or "",
                tool_calls=tool_calls,
            ),
            done=bool(data.get("done", True)),
            model=data.get("model"),
        )

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
