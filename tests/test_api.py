import time
from unittest.mock import MagicMock, patch
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import PyJWKClientError

from ai_agent.api.app import create_app
from ai_agent.api.auth import (
    AuthUnavailableError,
    AuthenticatedUser,
    InvalidTokenError,
    SupabaseJwtVerifier,
    build_verifier,
)
from ai_agent.api.serve import PublicBindError, assert_loopback_bind, main
from ai_agent.config import Settings

_ISSUER = "https://proj.supabase.co/auth/v1"
_USER_ID = "11111111-1111-4111-8111-111111111111"
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC = _PRIVATE.public_key()


class _SigningKey:
    def __init__(self, key: object):
        self.key = key


class _FakeVerifier:
    def verify(self, token: str) -> AuthenticatedUser:
        if token == "down":
            raise AuthUnavailableError("jwks down")
        if token != "good":
            raise InvalidTokenError("rejected")
        return AuthenticatedUser(user_id=_USER_ID)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "supabase_url": "",
        "supabase_anon_key": "",
        "supabase_jwt_secret": "",
    }
    values.update(overrides)
    return Settings(**values)


def _token(
    *,
    key: object = _PRIVATE,
    algorithm: str = "RS256",
    issuer: str = _ISSUER,
    audience: str = "authenticated",
    subject: object = _USER_ID,
    expires_in: int = 600,
) -> str:
    now = int(time.time())
    payload = {
        "sub": subject,
        "aud": audience,
        "iss": issuer,
        "iat": now,
        "exp": now + expires_in,
    }
    encoded = jwt.encode(payload, key, algorithm=algorithm)
    assert isinstance(encoded, str)
    return encoded


def _verifier(**kwargs: object) -> tuple[SupabaseJwtVerifier, MagicMock]:
    client = MagicMock()
    client.get_signing_key_from_jwt.return_value = _SigningKey(_PUBLIC)
    verifier = SupabaseJwtVerifier(
        "https://proj.supabase.co/",
        jwks_client=client,
        **kwargs,
    )
    return verifier, client


def test_health_is_public_and_minimal() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_me_requires_a_bearer_token() -> None:
    app = create_app(_settings(supabase_url="https://proj.supabase.co"))
    with TestClient(app) as client:
        missing = client.get("/api/me")
        empty = client.get("/api/me", headers={"Authorization": "Bearer "})
    assert missing.status_code == 401
    assert empty.status_code == 401
    assert missing.json()["detail"] == "Missing bearer token."


def test_me_reports_unconfigured_auth() -> None:
    app = create_app(_settings(), configure_auth=False)
    with TestClient(app) as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer good"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication is not configured."


def test_me_returns_the_verified_user_id() -> None:
    app = create_app(_settings(), _FakeVerifier())
    with TestClient(app) as client:
        ok = client.get("/api/me", headers={"Authorization": "Bearer good"})
        rejected = client.get("/api/me", headers={"Authorization": "Bearer no"})
        unavailable = client.get("/api/me", headers={"Authorization": "Bearer down"})
    assert ok.status_code == 200
    assert ok.json() == {"user_id": _USER_ID}
    assert rejected.status_code == 401
    assert unavailable.status_code == 503


def test_rs256_token_returns_supabase_user_id() -> None:
    verifier, client = _verifier()
    user = verifier.verify(_token())
    assert user.user_id == str(UUID(_USER_ID))
    client.get_signing_key_from_jwt.assert_called_once()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expires_in": -120},
        {"issuer": "https://other.supabase.co/auth/v1"},
        {"audience": "anon"},
        {"subject": "not-a-user"},
    ],
    ids=["expired", "issuer", "audience", "subject"],
)
def test_rs256_token_is_rejected(kwargs: dict[str, object]) -> None:
    verifier, _client = _verifier()
    with pytest.raises(InvalidTokenError):
        verifier.verify(_token(**kwargs))  # type: ignore[arg-type]


def test_unsupported_algorithm_is_rejected() -> None:
    verifier, client = _verifier()
    token = _token(key="h" * 64, algorithm="HS512")
    with pytest.raises(InvalidTokenError, match="Unsupported"):
        verifier.verify(token)
    client.get_signing_key_from_jwt.assert_not_called()


def test_hs256_uses_the_legacy_secret() -> None:
    secret = "s" * 32
    verifier, client = _verifier(jwt_secret=secret)
    user = verifier.verify(_token(key=secret, algorithm="HS256"))
    assert user.user_id == _USER_ID
    client.get_signing_key_from_jwt.assert_not_called()


def test_hs256_without_secret_is_rejected() -> None:
    verifier, _client = _verifier()
    with pytest.raises(InvalidTokenError, match="SUPABASE_JWT_SECRET"):
        verifier.verify(_token(key="s" * 32, algorithm="HS256"))


def test_jwks_fetch_failure_is_unavailable() -> None:
    verifier, client = _verifier()
    client.get_signing_key_from_jwt.side_effect = PyJWKClientError("down")
    with pytest.raises(AuthUnavailableError):
        verifier.verify(_token())


def test_malformed_token_is_rejected() -> None:
    verifier, _client = _verifier()
    with pytest.raises(InvalidTokenError, match="Malformed"):
        verifier.verify("not-a-jwt")


def test_build_verifier_is_absent_without_a_project_url() -> None:
    assert build_verifier(_settings()) is None
    verifier = build_verifier(_settings(supabase_url="https://proj.supabase.co/"))
    assert verifier is not None
    assert verifier.issuer == _ISSUER


def test_jwks_client_sends_the_publishable_key() -> None:
    with patch("ai_agent.api.auth.PyJWKClient") as client_cls:
        SupabaseJwtVerifier(
            "https://proj.supabase.co",
            anon_key="publishable",
        )
    client_cls.assert_called_once_with(
        f"{_ISSUER}/.well-known/jwks.json",
        headers={"apikey": "publishable"},
        timeout=5,
    )


def test_loopback_bind_accepts_only_local_addresses() -> None:
    for host in ("127.0.0.1", "localhost", "::1", "Localhost"):
        assert_loopback_bind(host, 8000)
    with pytest.raises(PublicBindError):
        assert_loopback_bind("0.0.0.0", 8000)
    with pytest.raises(PublicBindError):
        assert_loopback_bind("127.0.0.1", 0)


def test_main_refuses_a_public_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_BIND_HOST", "0.0.0.0")
    with patch("ai_agent.api.serve.uvicorn.run") as run:
        assert main() == 1
    run.assert_not_called()


def test_main_starts_uvicorn_on_loopback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("API_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("API_BIND_PORT", "8765")
    monkeypatch.setenv("CONVERSATION_DATABASE", f"sqlite:///{tmp_path / 'conversations.db'}")
    with patch("ai_agent.api.serve.uvicorn.run") as run:
        assert main() == 0
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["port"] == 8765
