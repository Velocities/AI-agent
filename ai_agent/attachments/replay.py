"""Which historical images are sent to the model on one turn."""

from __future__ import annotations

from ai_agent.conversations.store import Message


def image_parts(metadata: dict) -> list[dict]:
    raw = metadata.get("attachments")
    if not isinstance(raw, list):
        return []
    parts: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "image":
            continue
        if not isinstance(item.get("id"), str) or not item["id"]:
            continue
        parts.append(item)
    return parts


def select_replay_message_ids(
    records: list[Message],
    *,
    current_images: int,
    current_bytes: int,
    max_messages: int,
    max_images: int,
    max_bytes: int,
) -> set[str]:
    """Ids of historical user messages whose images all fit the remaining budget.

    Only the newest `max_messages` image-bearing user messages are candidates.
    A candidate is included only when every one of its images fits. A candidate
    that does not fit is skipped, and older candidates in the window are still
    considered. Current-turn images are not in `records`; their cost is reserved
    by `current_images` and `current_bytes`.
    """
    bearing: list[tuple[Message, list[dict]]] = []
    for record in records:
        if record.role != "user":
            continue
        parts = image_parts(record.metadata)
        if parts:
            bearing.append((record, parts))
    if max_messages <= 0:
        return set()
    candidates = bearing[-max_messages:]
    remaining_images = max_images - current_images
    remaining_bytes = max_bytes - current_bytes
    chosen: set[str] = set()
    for record, parts in reversed(candidates):
        count = len(parts)
        size = sum(_byte_size(part) for part in parts)
        if count <= remaining_images and size <= remaining_bytes:
            chosen.add(record.id)
            remaining_images -= count
            remaining_bytes -= size
    return chosen


def _byte_size(part: dict) -> int:
    value = part.get("byte_size")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)
