from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import jwt
from jwt import PyJWKClient, PyJWKClientError

from ai_agent.config import Settings


class InvalidTokenError(Exception):
    """The bearer token is missing, malformed, expired, or not ours."""


class AuthUnavailableError(Exception):
    """Signing keys could not be fetched. The token itself was not judged."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str


class TokenVerifier(Protocol):
    """Checks a bearer token. Implementations raise InvalidTokenError or AuthUnavailableError."""

    def verify(self, token: str) -> AuthenticatedUser: ...


class SupabaseJwtVerifier:
    """Verify a Supabase access token and return its user id (`sub`).

    Current projects sign with asymmetric keys published at the project's
    JWKS URL. Legacy projects sign with HS256 and `SUPABASE_JWT_SECRET`.
    """

    def __init__(
        self,
        supabase_url: str,
        *,
        audience: str = "authenticated",
        anon_key: str = "",
        jwt_secret: str = "",
        jwks_client: PyJWKClient | None = None,
    ):
        base = supabase_url.strip().rstrip("/")
        if not base:
            raise ValueError("SUPABASE_URL is required to verify tokens.")
        self.issuer = f"{base}/auth/v1"
        self.audience = audience.strip() or "authenticated"
        self.jwt_secret = jwt_secret.strip()
        if jwks_client is not None:
            self._jwks = jwks_client
        else:
            headers = {"apikey": anon_key.strip()} if anon_key.strip() else None
            self._jwks = PyJWKClient(
                f"{self.issuer}/.well-known/jwks.json",
                headers=headers,
                timeout=5,
            )

    def verify(self, token: str) -> AuthenticatedUser:
        if not token or not token.strip():
            raise InvalidTokenError("Missing bearer token.")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Malformed token.") from exc

        algorithm = header.get("alg")
        if algorithm == "HS256":
            key: object = self.jwt_secret
            algorithms = ["HS256"]
            if not self.jwt_secret:
                raise InvalidTokenError(
                    "Legacy HS256 tokens require SUPABASE_JWT_SECRET."
                )
        elif algorithm in {"RS256", "ES256", "EdDSA"}:
            try:
                key = self._jwks.get_signing_key_from_jwt(token).key
            except PyJWKClientError as exc:
                raise AuthUnavailableError("Could not fetch signing keys.") from exc
            algorithms = [algorithm]
        else:
            raise InvalidTokenError("Unsupported token algorithm.")

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=self.audience,
                issuer=self.issuer,
                leeway=10,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Invalid or expired token.") from exc

        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise InvalidTokenError("Token subject is not a user id.")
        try:
            user_id = str(UUID(subject))
        except ValueError as exc:
            raise InvalidTokenError("Token subject is not a user id.") from exc
        return AuthenticatedUser(user_id=user_id)


def build_verifier(settings: Settings) -> SupabaseJwtVerifier | None:
    """Return a verifier, or None when SUPABASE_URL is unset."""
    if not settings.supabase_url.strip():
        return None
    return SupabaseJwtVerifier(
        settings.supabase_url,
        audience=settings.supabase_jwt_audience,
        anon_key=settings.supabase_anon_key,
        jwt_secret=settings.supabase_jwt_secret,
    )
