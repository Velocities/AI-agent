"""Stage images for the next chat line.

Client-side metadata stripping is intentionally not implemented. The server
strips by default. See docs/vision-and-attachments.md section 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_agent.attachments.store import (
    DEFAULT_ATTACHMENT_REPLAY_MAX_BYTES,
    DEFAULT_ATTACHMENT_REPLAY_MAX_IMAGES,
)
from ai_agent.images import (
    DEFAULT_IMAGE_MAX_BYTES,
    DEFAULT_IMAGE_MAX_COUNT,
    DEFAULT_IMAGE_MAX_DIMENSION,
    DEFAULT_IMAGE_MAX_PIXELS,
    ImageRejected,
    validate_image_bytes,
)
from ai_agent.llm.client.types import ImageInput


def maybe_strip_for_transit(image: ImageInput) -> ImageInput:
    # TODO: client-side metadata strip; server still strips (docs/vision-and-attachments.md §3).
    return image


@dataclass
class StageCommand:
    handled: bool
    message: str = ""
    error: bool = False
    dim: bool = False


@dataclass
class ImageStage:
    """Process-local files waiting for the next turn.

    `vision` False rejects `/attach`. `vision` None means the caller could not
    probe a model document (the in-process REPL on the model host) and attach
    is still allowed after the bytes validate.
    """

    vision: bool | None = None
    max_bytes: int = DEFAULT_IMAGE_MAX_BYTES
    max_count: int = DEFAULT_IMAGE_MAX_COUNT
    max_pixels: int = DEFAULT_IMAGE_MAX_PIXELS
    max_dimension: int = DEFAULT_IMAGE_MAX_DIMENSION
    replay_max_bytes: int = DEFAULT_ATTACHMENT_REPLAY_MAX_BYTES
    replay_max_images: int = DEFAULT_ATTACHMENT_REPLAY_MAX_IMAGES
    images: list[ImageInput] = field(default_factory=list)
    names: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.images.clear()
        self.names.clear()

    def take(self) -> list[ImageInput]:
        staged = list(self.images)
        self.clear()
        return staged

    def handle(self, line: str) -> StageCommand:
        kind, argument = _command(line)
        if kind is None:
            return StageCommand(handled=False)
        if kind == "usage":
            return StageCommand(handled=True, message="Usage: /attach PATH", error=True)
        if kind == "clear":
            self.clear()
            return StageCommand(handled=True, message="Staged images cleared.", dim=True)
        if self.vision is False:
            return StageCommand(
                handled=True,
                message="This server's model does not accept images.",
                error=True,
            )
        path = Path(argument).expanduser()
        if not path.is_file():
            raise ImageRejected(f"Image file not found: {argument}")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ImageRejected(f"Could not read image file: {argument}") from exc
        image = validate_image_bytes(
            data,
            max_bytes=self.max_bytes,
            max_pixels=self.max_pixels,
            max_dimension=self.max_dimension,
        )
        image = maybe_strip_for_transit(image)
        limit = min(self.max_count, self.replay_max_images)
        if len(self.images) >= limit:
            raise ImageRejected(f"Too many images (max {limit}).")
        total = sum(len(item.data) for item in self.images) + len(image.data)
        if total > self.replay_max_bytes:
            raise ImageRejected(
                "Images exceed the per-turn size limit.",
                status_code=413,
            )
        self.images.append(image)
        self.names.append(path.name)
        return StageCommand(
            handled=True,
            message=(
                f"image file {path.name} will be attached as part of the next message in this chat"
            ),
        )


def _command(line: str) -> tuple[str | None, str]:
    if line == "/detach" or line == "/attach --clear":
        return "clear", ""
    if line == "/attach":
        return "usage", ""
    if not line.startswith("/attach "):
        return None, ""
    argument = line[len("/attach ") :].strip()
    if argument == "--clear" or not argument:
        return ("clear" if argument == "--clear" else "usage"), ""
    if len(argument) >= 2 and argument[0] == argument[-1] and argument[0] in {"'", '"'}:
        argument = argument[1:-1]
    return "add", argument
