from __future__ import annotations

from collections.abc import Callable

from ai_agent.agent.tools import COMMAND_DUMP_NUDGE, SCHEMA_NUDGE
from ai_agent.conversations.store import Message
from ai_agent.llm.client.types import ImageInput, LLMMessage, ToolCall

_INTERNAL_USER_PROMPTS = frozenset({SCHEMA_NUDGE, COMMAND_DUMP_NUDGE})


def message_payload(record: Message) -> dict:
    """JSON shape of a stored message, shared by the REST list and the turn stream."""
    return {
        "id": record.id,
        "role": record.role,
        "content": record.content,
        "created_at": record.created_at.isoformat(),
        "metadata": record.metadata,
        "position": record.position,
    }


def message_metadata(message: LLMMessage) -> dict:
    metadata: dict = {}
    if message.role == "user" and message.content in _INTERNAL_USER_PROMPTS:
        metadata["internal"] = True
    if message.tool_calls:
        metadata["tool_calls"] = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        metadata["tool_call_id"] = message.tool_call_id
    if message.name:
        metadata["name"] = message.name
    if message.images:
        # Bytes stay out of the transcript. `id` is set once the file is stored
        # so a later turn can replay it under the attachment budgets.
        metadata["attachments"] = [_attachment_metadata(image) for image in message.images]
    return metadata


def _attachment_metadata(image: ImageInput) -> dict:
    payload = {
        "kind": "image",
        "media_type": image.media_type,
        "byte_size": len(image.data),
    }
    if image.attachment_id:
        payload["id"] = image.attachment_id
    return payload


def message_from_record(
    record: Message,
    *,
    loader: Callable[[str], ImageInput | None] | None = None,
    include_images: bool = False,
) -> LLMMessage:
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
    images: list[ImageInput] = []
    if include_images and loader is not None:
        images = _load_images(record, loader)
    return LLMMessage(
        role=record.role,
        content=record.content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
        name=name if isinstance(name, str) else None,
        images=images,
    )


def _load_images(record: Message, loader: Callable[[str], ImageInput | None]) -> list[ImageInput]:
    raw = record.metadata.get("attachments")
    if not isinstance(raw, list):
        return []
    images: list[ImageInput] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("kind") != "image":
            continue
        attachment_id = item.get("id")
        if not isinstance(attachment_id, str) or not attachment_id:
            continue
        loaded = loader(attachment_id)
        if loaded is not None:
            images.append(loaded)
    return images
