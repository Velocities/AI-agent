"""CLI /attach staging."""

from pathlib import Path

import httpx

from ai_agent.cli.image_stage import ImageStage, maybe_strip_for_transit
from ai_agent.llm.client.types import ImageInput
from ai_agent_cli.api_client import AgentApiClient
from tests.test_images import jpeg_bytes, png_bytes


def test_attach_confirms_the_filename_and_sends_on_the_next_line(tmp_path: Path) -> None:
    shot = tmp_path / "nested" / "screenshot.png"
    shot.parent.mkdir()
    shot.write_bytes(png_bytes())
    other = tmp_path / "after.png"
    other.write_bytes(jpeg_bytes())
    stage = ImageStage(vision=True)
    first = stage.handle(f"/attach {shot}")
    second = stage.handle(f"/attach {other}")
    assert first.message == (
        "image file screenshot.png will be attached as part of the next message in this chat"
    )
    assert "/nested" not in first.message
    assert str(shot) not in first.message
    assert "after.png" in second.message
    images = stage.take()
    assert stage.images == []
    assert [image.media_type for image in images] == ["image/png", "image/jpeg"]
    assert maybe_strip_for_transit(images[0]) == images[0]

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read()
        return httpx.Response(200, text='{"type":"done","message":"ok"}\n')

    client = AgentApiClient("http://example.test", "token")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    list(client.stream_turn("chat", "Compare these", images))
    assert images[0].data in seen["body"]
    assert images[1].data in seen["body"]
    assert b"Compare these" in seen["body"]


def test_detach_new_and_at_path_are_not_inline_attach(tmp_path: Path) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(png_bytes())
    stage = ImageStage(vision=True)
    stage.handle(f"/attach {path}")
    cleared = stage.handle("/detach")
    assert cleared.dim is True
    assert stage.images == []
    stage.handle(f"/attach {path}")
    stage.clear()
    assert stage.handle("/new").handled is False
    literal = stage.handle("@shot.png hello")
    assert literal.handled is False
    assert stage.take() == []
    usage = stage.handle("/attach")
    assert usage.error is True
    assert "PATH" in usage.message
    blind = ImageStage(vision=False)
    refused = blind.handle(f"/attach {path}")
    assert refused.error is True
    assert "does not accept images" in refused.message
    assert blind.images == []
    assert isinstance(ImageInput(data=png_bytes(), media_type="image/png"), ImageInput)
