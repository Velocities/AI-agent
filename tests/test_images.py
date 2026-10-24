import base64
import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ai_agent.agent.loop import AgentLoop, AgentRunResult
from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
from ai_agent.api.transcript import message_from_record, message_metadata
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.attachments.cache import AttachmentCache
from ai_agent.attachments.os_store import OSAttachmentStore
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.conversations.attachments import AttachmentCatalog
from ai_agent.conversations.db import open_store_at
from ai_agent.images import ImageRejected, strip_image_metadata, validate_image_bytes
from ai_agent.llm.base import ImageInput, LLMMessage, LLMResponse
from ai_agent.llm.capabilities import ModelInfo
from ai_agent.llm.client.provider import FacadeLlmClient
from ai_agent.llm.http.errors import LLMErrorKind
from ai_agent.llm.http.session import LlmHttpSession, LlmSessionError
from ai_agent.llm.server.engine.ollama import OllamaEngine
from ai_agent.llm.server.engine.vllm import VLLMEngine
from ai_agent.llm.vision import canonical_image_fields, ollama_message, openai_content
from ai_agent.policy.engine import PolicyEngine
from ai_agent_cli.api_client import AgentApiClient

ALICE = "11111111-1111-4111-8111-111111111111"


def _image_bytes(fmt: str, **save_kwargs) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), (12, 34, 56)).save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


def png_bytes() -> bytes:
    return _image_bytes("PNG")


def jpeg_bytes() -> bytes:
    return _image_bytes("JPEG", quality=95)


def webp_bytes() -> bytes:
    return _image_bytes("WEBP", lossless=True)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class _Tokens:
    def verify(self, token: str) -> AuthenticatedUser:
        if token != "alice":
            raise InvalidTokenError("no")
        return AuthenticatedUser(user_id=ALICE)


class _CapturingAgent:
    def __init__(self, **_kwargs) -> None:
        self.messages: list[LLMMessage] = []
        self.on_message = None
        self.should_stop = None
        self.llm = None
        self.images: list[ImageInput] | None = None

    def run(self, content: str, stream_callback=None, images=None, **_kwargs) -> AgentRunResult:
        self.images = list(images or [])
        user = LLMMessage(role="user", content=content, images=self.images)
        self.messages.append(user)
        if self.on_message is not None:
            self.on_message(user)
        if stream_callback is not None:
            stream_callback("Seen")
        reply = LLMMessage(role="assistant", content="Seen")
        self.messages.append(reply)
        if self.on_message is not None:
            self.on_message(reply)
        return AgentRunResult(final_message="Seen", iterations=1)


def _api(tmp_path: Path, *, vision: bool = True):
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    catalog = AttachmentCatalog(store.engine)
    root = tmp_path / "attachments"
    blobs = OSAttachmentStore(root, catalog)
    cache = AttachmentCache(blobs, max_bytes=1024 * 1024)
    app = create_app(
        Settings(),
        _Tokens(),
        store=store,
        model_info=_model_info(vision=vision),
        attachment_store=blobs,
        attachment_catalog=catalog,
        attachment_cache=cache,
    )
    holder: dict[str, _CapturingAgent] = {}

    def factory(**_kwargs):
        holder["agent"] = _CapturingAgent()
        return holder["agent"]

    app.state.agent_factory = factory
    return TestClient(app), store, holder


def _model_info(*, vision: bool) -> ModelInfo:
    capabilities = {"completion", "tools"}
    if vision:
        capabilities.add("vision")
    return ModelInfo(
        engine="ollama",
        model="test",
        upstream="http://127.0.0.1:9",
        capabilities=frozenset(capabilities),
        vision=vision,
        tools=True,
        vision_source="probed",
        tools_source="probed",
        vision_verified=vision,
        tools_verified=True,
    )


def test_text_only_message_has_no_images() -> None:
    message = LLMMessage(role="user", content="Explain this screenshot.")
    assert message.content == "Explain this screenshot."
    assert message.images == []


def test_message_keeps_one_image() -> None:
    image = ImageInput(data=png_bytes(), media_type="image/png")
    message = LLMMessage(
        role="user",
        content="What's wrong with this screenshot?",
        images=[image],
    )
    assert message.images == [image]


def test_message_keeps_multiple_images() -> None:
    images = [
        ImageInput(data=png_bytes(), media_type="image/png"),
        ImageInput(data=jpeg_bytes(), media_type="image/jpeg"),
    ]
    message = LLMMessage(role="user", content="Compare these.", images=images)
    assert message.images == images


def test_image_lists_are_not_shared() -> None:
    first = LLMMessage(role="user", content="one")
    second = LLMMessage(role="user", content="two")
    first.images.append(ImageInput(data=b"x", media_type="image/png"))
    assert second.images == []


def test_valid_png_jpeg_and_webp() -> None:
    png = validate_image_bytes(png_bytes(), declared_type="image/png")
    jpeg = validate_image_bytes(jpeg_bytes(), declared_type="image/jpeg")
    webp = validate_image_bytes(webp_bytes(), declared_type="image/webp")
    assert (png.media_type, jpeg.media_type, webp.media_type) == (
        "image/png",
        "image/jpeg",
        "image/webp",
    )
    assert jpeg.data == jpeg_bytes()


def test_media_type_comes_from_bytes_not_the_filename() -> None:
    image = validate_image_bytes(jpeg_bytes(), declared_type="application/octet-stream")
    assert image.media_type == "image/jpeg"


def test_unsupported_mime_type() -> None:
    with pytest.raises(ImageRejected, match="Unsupported image type: image/gif") as caught:
        validate_image_bytes(b"GIF89a\x01\x00\x01\x00", declared_type="image/gif")
    assert caught.value.status_code == 400


def test_oversized_image() -> None:
    data = png_bytes()
    with pytest.raises(ImageRejected, match="exceeds the limit of 8 bytes") as caught:
        validate_image_bytes(data, max_bytes=8)
    assert caught.value.status_code == 413


def test_invalid_image_data() -> None:
    with pytest.raises(ImageRejected, match="Invalid image data."):
        validate_image_bytes(b"not an image", declared_type="image/png")
    with pytest.raises(ImageRejected, match="Invalid image data."):
        validate_image_bytes(b"\x89PNG\r\n\x1a\ntruncated", declared_type="image/png")


def test_declared_type_must_match_the_bytes() -> None:
    with pytest.raises(ImageRejected, match="Invalid image data."):
        validate_image_bytes(jpeg_bytes(), declared_type="image/png")


def test_ollama_request_uses_raw_base64_and_keeps_text() -> None:
    raw = png_bytes()
    other = jpeg_bytes()
    message = {
        "role": "user",
        "content": "What's wrong with this UI?",
        **canonical_image_fields(
            [
                ImageInput(data=raw, media_type="image/png"),
                ImageInput(data=other, media_type="image/jpeg"),
            ]
        ),
    }
    prepared = ollama_message(message)
    assert prepared == {
        "role": "user",
        "content": "What's wrong with this UI?",
        "images": [_b64(raw), _b64(other)],
    }
    assert base64.b64decode(prepared["images"][0]) == raw
    assert prepared["images"][0] != _b64(_b64(raw).encode())


def test_ollama_text_only_message_is_unchanged() -> None:
    message = {"role": "user", "content": "hello"}
    assert ollama_message(message) is message


def test_ollama_engine_sends_images_and_streams_the_reply() -> None:
    raw = png_bytes()
    encoded = _b64(raw)

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_lines(self):
            yield json.dumps(
                {
                    "model": "llava",
                    "message": {"role": "assistant", "content": "The title is clipped."},
                    "done": True,
                }
            )

    session = MagicMock()
    session.base_url = "http://localhost:11434"
    session.stream_post.return_value = _Stream()
    engine = OllamaEngine(session, "llava")
    payload = {
        "model": "llava",
        "messages": [
            {
                "role": "user",
                "content": "What's wrong with this UI?",
                "images": [encoded],
                "image_media_types": ["image/png"],
            }
        ],
        "stream": True,
    }
    lines = list(engine.chat_lines(payload))
    sent = session.stream_post.call_args.args[1]
    assert sent["messages"] == [
        {
            "role": "user",
            "content": "What's wrong with this UI?",
            "images": [encoded],
        }
    ]
    assert json.loads(lines[0])["message"]["content"] == "The title is clipped."


def test_ollama_engine_leaves_text_only_messages_unchanged() -> None:
    session = MagicMock()
    session.stream_post.return_value = _EmptyStream()
    engine = OllamaEngine(session, "qwen3:14b")
    message = {"role": "user", "content": "hello"}
    list(
        engine.chat_lines(
            {"model": "qwen3:14b", "messages": [message], "stream": True}
        )
    )
    sent = session.stream_post.call_args.args[1]
    assert sent["messages"] == [message]
    assert "images" not in sent["messages"][0]


def test_ollama_engine_propagates_provider_errors() -> None:
    session = MagicMock()
    session.stream_post.side_effect = LlmSessionError(
        LLMErrorKind.HTTP,
        "LLM HTTP error: 400",
    )
    engine = OllamaEngine(session, "qwen3:14b")
    raw = png_bytes()
    with pytest.raises(LlmSessionError, match="LLM HTTP error: 400"):
        list(
            engine.chat_lines(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "Look",
                            "images": [_b64(raw)],
                            "image_media_types": ["image/png"],
                        }
                    ]
                }
            )
        )
    sent = session.stream_post.call_args.args[1]
    assert sent["messages"][0]["images"] == [_b64(raw)]


def test_vllm_request_uses_image_url_data_uri() -> None:
    raw = png_bytes()
    other = webp_bytes()
    message = {
        "role": "user",
        "content": "What's wrong with this UI?",
        **canonical_image_fields(
            [
                ImageInput(data=raw, media_type="image/png"),
                ImageInput(data=other, media_type="image/webp"),
            ]
        ),
    }
    assert openai_content(message) == [
        {"type": "text", "text": "What's wrong with this UI?"},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{_b64(raw)}"},
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/webp;base64,{_b64(other)}"},
        },
    ]


def test_vllm_text_only_content_stays_a_string() -> None:
    assert openai_content({"role": "user", "content": "hello"}) == "hello"


def test_vllm_engine_sends_multimodal_body_and_streams() -> None:
    raw = png_bytes()
    encoded = _b64(raw)
    sse = [
        'data: {"model":"vision","choices":[{"delta":{"content":"Overlap"},"finish_reason":null}]}',
        'data: {"model":"vision","choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    session = MagicMock()
    session.base_url = "http://localhost:8000"
    session.stream_post.return_value = _LineStream(sse)
    engine = VLLMEngine(session, "vision")
    lines = list(
        engine.chat_lines(
            {
                "model": "vision",
                "messages": [
                    {
                        "role": "user",
                        "content": "What's wrong with this UI?",
                        "images": [encoded],
                        "image_media_types": ["image/png"],
                    }
                ],
                "stream": True,
            }
        )
    )
    sent = session.stream_post.call_args.args[1]
    assert session.stream_post.call_args.args[0] == "/v1/chat/completions"
    assert sent["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What's wrong with this UI?"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                },
            ]
        }
    ]
    assert "images" not in sent["messages"][0]
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["message"]["content"] == "Overlap"
    assert payloads[-1]["done"] is True


class _EmptyStream:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield json.dumps(
            {
                "model": "qwen3:14b",
                "message": {"role": "assistant", "content": "hi"},
                "done": True,
            }
        )


class _LineStream:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self):
        yield from self._lines


def test_facade_streams_a_multimodal_request(monkeypatch) -> None:
    raw = png_bytes()
    captured: dict = {}

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield json.dumps(
                {
                    "model": "vision",
                    "message": {"role": "assistant", "content": "Clipped title."},
                    "done": True,
                    "done_reason": "stop",
                }
            )

    class _Client:
        def __init__(self, timeout) -> None:
            del timeout

        def stream(self, method: str, url: str, json: dict):
            assert method == "POST"
            assert url.endswith("/api/chat")
            captured["payload"] = json
            return _Stream()

        def close(self) -> None:
            return None

    monkeypatch.setattr(httpx, "Client", _Client)
    provider = FacadeLlmClient(LlmHttpSession("http://127.0.0.1:9"), "vision")
    image = ImageInput(data=raw, media_type="image/png")
    chunks = list(
        provider.chat_stream(
            [LLMMessage(role="user", content="What's wrong?", images=[image])]
        )
    )
    message = captured["payload"]["messages"][0]
    assert message["content"] == "What's wrong?"
    assert message["images"] == [_b64(raw)]
    assert message["image_media_types"] == ["image/png"]
    assert isinstance(message["content"], str)
    assert chunks[0].content_delta == "Clipped title."
    assert chunks[-1].done is True
    assert chunks[-1].response is not None
    assert chunks[-1].response.message.content == "Clipped title."


def test_facade_text_only_request_omits_images(monkeypatch) -> None:
    captured: dict = {}

    class _Client:
        def __init__(self, timeout) -> None:
            del timeout

        def stream(self, method: str, url: str, json: dict):
            del method, url
            captured["payload"] = json
            line = (
                '{"model":"vision","message":{"role":"assistant","content":"hi"},"done":true}'
            )
            return _LineStream([line])

        def close(self) -> None:
            return None

    monkeypatch.setattr(httpx, "Client", _Client)
    provider = FacadeLlmClient(LlmHttpSession("http://127.0.0.1:9"), "vision")
    list(provider.chat_stream([LLMMessage(role="user", content="hello")]))
    message = captured["payload"]["messages"][0]
    assert message == {"role": "user", "content": "hello"}


def test_agent_passes_images_to_the_provider_unchanged(tmp_path: Path) -> None:
    settings = Settings()
    settings.agent_max_iterations = 2
    policy = PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")
    executor = CommandExecutor(
        timeout=5,
        output_limit=1024,
        scratch_dir=tmp_path / "scratch",
    )
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(role="assistant", content="The title is clipped.")
    )
    agent = AgentLoop(
        settings=settings,
        llm=llm,
        policy=policy,
        executor=executor,
        audit=AuditLogger(log_path=tmp_path / "audit.jsonl", user="test"),
        prompter=ApprovalPrompter(settings.agent_confirmation_mode, ApprovalSession(), MagicMock()),
        session=ApprovalSession(),
    )
    image = ImageInput(data=png_bytes(), media_type="image/png")
    result = agent.run("What's wrong with this UI?", images=[image])
    sent = llm.chat.call_args.args[0]
    user = next(message for message in sent if message.role == "user")
    assert user.content == "What's wrong with this UI?"
    assert user.images == [image]
    assert result.final_message == "The title is clipped."


def test_history_keeps_an_attachment_reference_without_bytes() -> None:
    image = ImageInput(data=png_bytes(), media_type="image/png")
    message = LLMMessage(role="user", content="Look", images=[image])
    metadata = message_metadata(message)
    assert metadata["attachments"] == [
        {"kind": "image", "media_type": "image/png", "byte_size": len(image.data)}
    ]
    assert _b64(image.data) not in json.dumps(metadata)


def test_turn_upload_builds_a_multimodal_message(tmp_path: Path) -> None:
    client, store, holder = _api(tmp_path)
    png = png_bytes()
    jpeg = jpeg_bytes()
    headers = {"Authorization": "Bearer alice"}
    with client:
        conversation_id = client.post("/api/conversations", json={}, headers=headers).json()["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/turns",
            data={"content": "What's wrong with this screenshot?"},
            files=[
                ("images", ("screenshot.png", png, "image/png")),
                ("images", ("shot.png", jpeg, "application/octet-stream")),
            ],
            headers=headers,
        )
    assert response.status_code == 200
    agent = holder["agent"]
    assert agent.images is not None
    assert [image.media_type for image in agent.images] == ["image/png", "image/jpeg"]
    assert agent.images[0].data.startswith(b"\x89PNG")
    assert agent.images[1].data.startswith(b"\xff\xd8\xff")
    assert agent.images[0].attachment_id
    saved = store.list_messages(ALICE, conversation_id)
    assert saved[0].content == "What's wrong with this screenshot?"
    attachment = saved[0].metadata["attachments"][0]
    assert attachment["media_type"] == "image/png"
    assert attachment["kind"] == "image"
    assert attachment["id"] == agent.images[0].attachment_id
    assert _b64(png) not in json.dumps(saved[0].metadata)
    assert message_from_record(saved[0]).images == []


def test_turn_rejects_unsupported_oversized_and_invalid_images(tmp_path: Path) -> None:
    client, _store, _holder = _api(tmp_path)
    headers = {"Authorization": "Bearer alice"}
    with client:
        conversation_id = client.post("/api/conversations", json={}, headers=headers).json()["id"]
        url = f"/api/conversations/{conversation_id}/turns"
        gif = client.post(
            url,
            data={"content": "animate"},
            files=[("images", ("clip.gif", b"GIF89a\x01\x00\x01\x00", "image/gif"))],
            headers=headers,
        )
        client.app.state.settings = client.app.state.settings.model_copy(
            update={"image_max_bytes": 8}
        )
        huge = client.post(
            url,
            data={"content": "big"},
            files=[("images", ("shot.png", png_bytes(), "image/png"))],
            headers=headers,
        )
        client.app.state.settings = client.app.state.settings.model_copy(
            update={"image_max_bytes": 10 * 1024 * 1024}
        )
        garbage = client.post(
            url,
            data={"content": "nope"},
            files=[("images", ("shot.png", b"not-an-image", "image/png"))],
            headers=headers,
        )
    assert gif.status_code == 400
    assert gif.json()["detail"] == "Unsupported image type: image/gif"
    assert huge.status_code == 413
    assert "exceeds the limit of 8 bytes" in huge.json()["detail"]
    assert garbage.status_code == 400
    assert garbage.json()["detail"] == "Invalid image data."


def test_cli_client_uploads_images_as_multipart() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = request.read()
        return httpx.Response(
            200,
            text=json.dumps({"type": "done", "message": "ok"}) + "\n",
        )

    client = AgentApiClient("http://example.test", "token")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    image = ImageInput(data=png_bytes(), media_type="image/png")
    events = list(client.stream_turn("chat", "Explain this", [image]))
    assert events == [{"type": "done", "message": "ok"}]
    assert seen["content_type"].startswith("multipart/form-data")
    assert b"Explain this" in seen["body"]
    assert image.data in seen["body"]


def test_cli_client_keeps_text_only_turns_as_json() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = request.read()
        return httpx.Response(200, text=json.dumps({"type": "token", "text": "Hi"}) + "\n")

    client = AgentApiClient("http://example.test", "token")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    events = list(client.stream_turn("chat", "hello"))
    assert events == [{"type": "token", "text": "Hi"}]
    assert seen["content_type"].startswith("application/json")
    assert json.loads(seen["body"]) == {"content": "hello"}


def test_truncated_and_disallowed_images_are_rejected() -> None:
    from PIL import ImageFile

    assert ImageFile.LOAD_TRUNCATED_IMAGES is False
    samples = [
        b"\xff\xd8\xff\x00",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIH",
        b"RIFF\x00\x00\x00\x00WEBP",
        b"",
        b"BM" + b"\x00" * 8,
    ]
    for sample in samples:
        with pytest.raises(ImageRejected, match="Invalid image data.|Unsupported image type"):
            validate_image_bytes(sample)
    with pytest.raises(ImageRejected, match="Unsupported image type: image/gif"):
        validate_image_bytes(b"GIF89a\x01\x00\x01\x00")
    wide = io.BytesIO()
    Image.new("RGB", (2, 1), (1, 2, 3)).save(wide, format="PNG")
    with pytest.raises(ImageRejected, match="exceed the limit") as caught:
        validate_image_bytes(wide.getvalue(), max_dimension=1)
    assert caught.value.status_code == 413
    pixels = io.BytesIO()
    Image.new("RGB", (2, 2), (1, 2, 3)).save(pixels, format="PNG")
    with pytest.raises(ImageRejected, match="Invalid image data.") as caught:
        validate_image_bytes(pixels.getvalue(), max_pixels=3)
    assert caught.value.status_code == 413


def test_animated_webp_is_rejected() -> None:
    frames = [
        Image.new("RGB", (1, 1), (255, 0, 0)),
        Image.new("RGB", (1, 1), (0, 255, 0)),
    ]
    buffer = io.BytesIO()
    frames[0].save(
        buffer,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=50,
        loop=0,
    )
    with pytest.raises(ImageRejected, match="Invalid image data."):
        validate_image_bytes(buffer.getvalue())


def test_strip_removes_jpeg_gps_and_bakes_orientation() -> None:
    from PIL import ImageOps
    from PIL.ExifTags import IFD
    from PIL.TiffImagePlugin import IFDRational

    original = Image.new("RGB", (4, 2), (0, 0, 0))
    original.putpixel((0, 0), (255, 0, 0))
    original.putpixel((3, 1), (0, 0, 255))
    exif = original.getexif()
    exif[274] = 6
    gps = exif.get_ifd(IFD.GPSInfo)
    gps[1] = "N"
    gps[2] = (IFDRational(37, 1), IFDRational(48, 1), IFDRational(0, 1))
    gps[3] = "W"
    gps[4] = (IFDRational(122, 1), IFDRational(25, 1), IFDRational(0, 1))
    raw_buffer = io.BytesIO()
    original.save(raw_buffer, format="JPEG", quality=95, exif=exif)
    raw = raw_buffer.getvalue()
    assert Image.open(io.BytesIO(raw)).getexif().get_ifd(IFD.GPSInfo)
    checked = validate_image_bytes(raw)
    assert checked.data == raw
    stripped = strip_image_metadata(checked)
    assert stripped.media_type == "image/jpeg"
    assert not Image.open(io.BytesIO(stripped.data)).getexif().get_ifd(IFD.GPSInfo)
    validate_image_bytes(stripped.data, declared_type="image/jpeg")
    expected = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    actual = Image.open(io.BytesIO(stripped.data))
    assert actual.size == expected.size == (2, 4)
    for left, right in zip(expected.getdata(), actual.getdata(), strict=True):
        assert all(abs(a - b) <= 40 for a, b in zip(left, right, strict=True))


def test_strip_removes_png_text_and_keeps_it_when_skipped() -> None:
    from PIL import PngImagePlugin

    image = Image.new("RGB", (1, 1), (9, 9, 9))
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "gps-secret-marker")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    raw = buffer.getvalue()
    assert b"gps-secret-marker" in raw
    stripped = strip_image_metadata(validate_image_bytes(raw))
    assert stripped.media_type == "image/png"
    assert b"gps-secret-marker" not in stripped.data
    assert validate_image_bytes(raw).data == raw


def test_strip_removes_webp_exif_and_keeps_it_when_skipped() -> None:
    image = Image.new("RGB", (2, 2), (1, 2, 3))
    exif = image.getexif()
    exif[270] = "gps-secret-marker"
    exif[274] = 1
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=95, exif=exif)
    raw = buffer.getvalue()
    assert b"gps-secret-marker" in raw
    checked = validate_image_bytes(raw)
    assert checked.data == raw
    stripped = strip_image_metadata(checked)
    assert stripped.media_type == "image/webp"
    assert b"gps-secret-marker" not in stripped.data
    assert not Image.open(io.BytesIO(stripped.data)).getexif().get(270)


def test_strip_failure_does_not_return_the_original(monkeypatch) -> None:
    image = validate_image_bytes(jpeg_bytes())

    def boom(self, *args, **kwargs):
        raise OSError("cannot save")

    monkeypatch.setattr(Image.Image, "save", boom)
    with pytest.raises(ImageRejected, match="Invalid image data."):
        strip_image_metadata(image)
