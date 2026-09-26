from __future__ import annotations

from ai_agent.conversations.store import Message
from ai_agent.llm.base import LLMMessage, ToolCall


def message_metadata(message: LLMMessage) -> dict:
    metadata: dict = {}
    if message.tool_calls:
        metadata["tool_calls"] = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        metadata["tool_call_id"] = message.tool_call_id
    if message.name:
        metadata["name"] = message.name
    return metadata


def message_from_record(record: Message) -> LLMMessage:
    raw_calls = record.metadata.get("tool_calls") or []
    tool_calls = []
    if isinstance(raw_calls, list):
        for call in raw_calls:
            if not isinstance(call, dict):
                continue
            name = call.get("name")
            call_id = call.get("id")
            arguments = call.get("arguments")
            if not isinstance(name, str) or not isinstance(call_id, str):
                continue
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
    tool_call_id = record.metadata.get("tool_call_id")
    name = record.metadata.get("name")
    return LLMMessage(
        role=record.role,
        content=record.content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
        name=name if isinstance(name, str) else None,
    )
