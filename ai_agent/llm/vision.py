"""Translate ImageInput into each engine's chat request.

The agent loop only sees ImageInput. This module is the provider boundary:
the canonical chat body carries base64 plus a MIME type, Ollama receives a
flat base64 list, and vLLM receives OpenAI image_url parts.
"""

from __future__ import annotations

import base64
from typing import Any

from ai_agent.images import sniff_image_media_type
from ai_agent.llm.client.types import ImageInput
from ai_agent.llm.http.errors import LLMErrorKind
from ai_agent.llm.http.session import LlmSessionError


def canonical_image_fields(images: list[ImageInput]) -> dict[str, list[str]]:
    """Encode each image once for the canonical /api/chat body.

    `images` is raw base64, which is what Ollama's chat API stores.
    `image_media_types` travels with it so the vLLM adapter can build a
    data URI without encoding the bytes again. OllamaEngine strips that
    sidecar before the upstream request.
    """
    encoded: list[str] = []
    media_types: list[str] = []
    for image in images:
        encoded.append(base64.b64encode(image.data).decode("ascii"))
        media_types.append(image.media_type)
    return {"images": encoded, "image_media_types": media_types}


def ollama_message(message: dict[str, Any]) -> dict[str, Any]:
    """Return an Ollama chat message. Text-only messages are left as-is."""
    if "images" not in message and "image_media_types" not in message:
        return message
    prepared = {key: value for key, value in message.items() if key != "image_media_types"}
    images = prepared.get("images")
    if not images:
        prepared.pop("images", None)
        return prepared
    prepared["images"] = [_image_base64(item) for item in images]
    return prepared


def ollama_messages(messages: list[Any]) -> list[Any]:
    return [ollama_message(item) if isinstance(item, dict) else item for item in messages]


def openai_content(message: dict[str, Any]) -> Any:
    """OpenAI chat content. Text-only messages stay a plain string."""
    images = message.get("images") or []
    text = message.get("content", "")
    if not images:
        return text
    parts: list[dict[str, Any]] = []
    if isinstance(text, str) and text:
        parts.append({"type": "text", "text": text})
    media_types = message.get("image_media_types") or []
    if not isinstance(media_types, list):
        media_types = []
    for index, item in enumerate(images):
        media_type, data = _openai_image(item, index, media_types)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{data}"},
            }
        )
    return parts


def _image_base64(item: Any) -> str:
    if isinstance(item, str) and item:
        return item
    if isinstance(item, dict):
        data = item.get("data")
        if isinstance(data, str) and data:
            return data
    raise LlmSessionError(LLMErrorKind.PROTOCOL, "Image attachment is missing data.")


def _openai_image(
    item: Any,
    index: int,
    media_types: list[Any],
) -> tuple[str, str]:
    if isinstance(item, dict):
        data = item.get("data")
        media_type = item.get("media_type")
    else:
        data = item
        media_type = media_types[index] if index < len(media_types) else None
    if not isinstance(data, str) or not data:
        raise LlmSessionError(LLMErrorKind.PROTOCOL, "Image attachment is missing data.")
    if not isinstance(media_type, str) or not media_type:
        media_type = _media_type_from_base64(data)
    return media_type, data


def _media_type_from_base64(data: str) -> str:
    try:
        raw = base64.b64decode(data, validate=False)
    except (ValueError, TypeError):
        raw = b""
    sniffed = sniff_image_media_type(raw)
    return sniffed or "application/octet-stream"
