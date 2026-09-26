import pytest
from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser
from ai_agent.conversations.db import open_stores_at
from ai_agent.deployment.access import (
    ACCESS_DENIED_CODE,
    ACCESS_DENIED_MESSAGE,
    ACCESS_PENDING_CODE,
    ACCESS_PENDING_MESSAGE,
    AccessStatus,
)
from ai_agent.deployment.access_store import AccessGateError, DeploymentAccessStore

USER = "11111111-1111-4111-8111-111111111111"


class _Verifier:
    def verify(self, token: str) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=token)


@pytest.fixture
def access_store(tmp_path) -> DeploymentAccessStore:
    _store, access = open_stores_at(f"sqlite:///{tmp_path / 'db.sqlite3'}")
    return access


def test_authorize_creates_pending_once(access_store: DeploymentAccessStore) -> None:
    with pytest.raises(AccessGateError) as pending:
        access_store.authorize(USER)
    assert pending.value.code == ACCESS_PENDING_CODE
    with pytest.raises(AccessGateError):
        access_store.authorize(USER)
    rows = access_store.list_by_status(AccessStatus.PENDING)
    assert len(rows) == 1


def test_denied_user_cannot_re_request(access_store: DeploymentAccessStore) -> None:
    access_store.deny(USER)
    with pytest.raises(AccessGateError) as exc:
        access_store.authorize(USER)
    assert exc.value.code == ACCESS_DENIED_CODE


def test_approve_after_deny(access_store: DeploymentAccessStore) -> None:
    access_store.deny(USER)
    access_store.approve(USER)
    access_store.authorize(USER)


def test_api_me_pending(tmp_path, access_store: DeploymentAccessStore) -> None:
    _store, access = open_stores_at(f"sqlite:///{tmp_path / 'api.sqlite3'}")
    app = create_app(
        __import__("ai_agent.config", fromlist=["Settings"]).Settings(),
        _Verifier(),
        store=_store,
        access_store=access,
    )
    with TestClient(app) as client:
        response = client.get("/api/me", headers={"Authorization": f"Bearer {USER}"})
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == ACCESS_PENDING_CODE
    assert ACCESS_PENDING_MESSAGE.split(".")[0] in detail["message"]


def test_api_me_approved(tmp_path) -> None:
    store, access = open_stores_at(f"sqlite:///{tmp_path / 'ok.sqlite3'}")
    access.approve(USER)
    app = create_app(
        __import__("ai_agent.config", fromlist=["Settings"]).Settings(),
        _Verifier(),
        store=store,
        access_store=access,
    )
    with TestClient(app) as client:
        response = client.get("/api/me", headers={"Authorization": f"Bearer {USER}"})
    assert response.status_code == 200
    assert response.json() == {"user_id": USER}


def test_api_me_denied(tmp_path) -> None:
    store, access = open_stores_at(f"sqlite:///{tmp_path / 'no.sqlite3'}")
    access.deny(USER)
    app = create_app(
        __import__("ai_agent.config", fromlist=["Settings"]).Settings(),
        _Verifier(),
        store=store,
        access_store=access,
    )
    with TestClient(app) as client:
        response = client.get("/api/me", headers={"Authorization": f"Bearer {USER}"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == ACCESS_DENIED_CODE
    assert response.json()["detail"]["message"] == ACCESS_DENIED_MESSAGE
