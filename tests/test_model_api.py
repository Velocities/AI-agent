"""Model capability probe and GET /api/model."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
from ai_agent.cli.llm_serve import prepare_upstream
from ai_agent.config import LlmEngineKind, Settings
from ai_agent.conversations.db import open_store_at
from ai_agent.llm.capabilities import probe_model_info
from ai_agent.llm.server.engine.base import EngineHealth
from tests.test_images import _api, png_bytes

ALICE = "11111111-1111-4111-8111-111111111111"


class _Tokens:
    def verify(self, token: str) -> AuthenticatedUser:
        if token != "good":
            raise InvalidTokenError("no")
        return AuthenticatedUser(user_id=ALICE)


def test_ollama_probe_maps_capabilities() -> None:
    engine = MagicMock()
    engine.model = "qwen3.5:9b"
    engine.upstream_url = "http://127.0.0.1:11434"
    engine.show_model.return_value = {
        "capabilities": ["completion", "vision", "tools", "thinking", 1]
    }
    info = probe_model_info(
        engine,
        Settings(llm_engine=LlmEngineKind.OLLAMA, llm_model="qwen3.5:9b"),
        warmup_ok=True,
    )
    assert info.vision is True
    assert info.tools is True
    assert info.vision_source == "probed"
    assert info.tools_source == "probed"
    assert info.vision_verified is True
    assert info.tools_verified is True
    assert info.capabilities == frozenset({"completion", "vision", "tools", "thinking"})


def test_ollama_without_tools_fails_before_warmup() -> None:
    settings = Settings(llm_engine=LlmEngineKind.OLLAMA)
    console = MagicMock()
    engine = MagicMock()
    engine.engine_name = "Ollama"
    engine.model = "qwen2.5vl:7b"
    engine.healthcheck.return_value = EngineHealth(ok=True, message="ok")
    engine.show_model.return_value = {"capabilities": ["completion", "vision"]}
    with (
        patch("ai_agent.cli.llm_serve.create_engine", return_value=engine),
        patch("ai_agent.cli.llm_serve.warmup_engine") as warmup,
    ):
        assert prepare_upstream(settings, console) is None
    warmup.assert_not_called()
    engine.close.assert_called_once()


def test_vllm_vision_comes_from_configuration_not_the_model_name() -> None:
    engine = MagicMock()
    engine.model = "llava-onevision"
    engine.upstream_url = "http://127.0.0.1:8000"
    enabled = probe_model_info(
        engine,
        Settings(llm_engine=LlmEngineKind.VLLM, llm_model="llava-onevision", llm_vision=True),
        warmup_ok=True,
    )
    disabled = probe_model_info(
        engine,
        Settings(llm_engine=LlmEngineKind.VLLM, llm_model="llava-onevision", llm_vision=False),
        warmup_ok=True,
    )
    assert enabled.vision is True
    assert enabled.vision_source == "configured"
    assert enabled.vision_verified is False
    assert enabled.tools is True
    assert enabled.tools_source == "warmup"
    assert enabled.tools_verified is True
    assert "vision" in enabled.capabilities
    assert disabled.vision is False
    assert "vision" not in disabled.capabilities
    assert "vl" not in enabled.vision_source


def test_model_route_requires_a_token_and_a_snapshot(tmp_path: Path) -> None:
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    app = create_app(Settings(), _Tokens(), store=store)
    with TestClient(app) as client:
        missing = client.get("/api/model")
        unready = client.get("/api/model", headers={"Authorization": "Bearer good"})
    assert missing.status_code == 401
    assert unready.status_code == 503
    assert unready.json()["detail"] == "Model information is not available."


def test_model_route_returns_the_snapshot(tmp_path: Path) -> None:
    client, _store, _holder = _api(tmp_path, vision=True)
    with client:
        response = client.get("/api/model", headers={"Authorization": "Bearer alice"})
    assert response.status_code == 200
    body = response.json()
    assert body["vision"] is True
    assert body["tools"] is True
    assert body["vision_source"] == "probed"
    assert body["tools_verified"] is True
    assert body["capabilities"] == ["completion", "tools", "vision"]


def test_images_are_refused_when_vision_is_false_but_text_turns_work(tmp_path: Path) -> None:
    client, store, _holder = _api(tmp_path, vision=False)
    headers = {"Authorization": "Bearer alice"}
    with client:
        conversation_id = client.post("/api/conversations", json={}, headers=headers).json()["id"]
        images = client.post(
            f"/api/conversations/{conversation_id}/turns",
            data={"content": "look"},
            files=[("images", ("shot.png", png_bytes(), "image/png"))],
            headers=headers,
        )
        text = client.post(
            f"/api/conversations/{conversation_id}/turns",
            json={"content": "hello"},
            headers=headers,
        )
    assert images.status_code == 400
    assert images.json()["detail"] == "This model does not accept images."
    assert text.status_code == 200
    assert store.list_messages(ALICE, conversation_id)[0].content == "hello"
