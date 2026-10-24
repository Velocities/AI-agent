"""Per-user image metadata preference."""

from pathlib import Path

from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
from ai_agent.api.settings import read_settings
from ai_agent.config import Settings
from ai_agent.conversations.db import open_store_at

ALICE = "11111111-1111-4111-8111-111111111111"


class _Tokens:
    def verify(self, token: str) -> AuthenticatedUser:
        if token != "alice":
            raise InvalidTokenError("no")
        return AuthenticatedUser(user_id=ALICE)


def _client(tmp_path: Path) -> TestClient:
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    return TestClient(create_app(Settings(), _Tokens(), store=store))


def test_missing_row_strips_and_patch_is_strict(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer alice"}
    with _client(tmp_path) as client:
        anonymous = client.get("/api/me/settings")
        current = client.get("/api/me/settings", headers=headers)
        extra = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"strip_image_metadata": False, "theme": "dark"},
        )
        updated = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"strip_image_metadata": False},
        )
        again = client.get("/api/me/settings", headers=headers)
    assert anonymous.status_code == 401
    assert current.status_code == 200
    assert current.json() == {"strip_image_metadata": True}
    assert extra.status_code == 422
    assert updated.status_code == 200
    assert updated.json() == {"strip_image_metadata": False}
    assert again.json() == {"strip_image_metadata": False}
    assert "GPS" in (read_settings.__doc__ or "")


def test_settings_route_is_unavailable_without_a_store() -> None:
    app = create_app(Settings(), _Tokens(), store=None)
    with TestClient(app) as client:
        response = client.get("/api/me/settings", headers={"Authorization": "Bearer alice"})
    assert response.status_code == 503
