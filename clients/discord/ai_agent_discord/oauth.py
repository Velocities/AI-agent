"""Discord-through-Supabase sign-in for one bot process.

The browser returns to this process. The saved session is stored for the
Discord user who ran /login, and only when the Supabase token is for that
same Discord account.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx

from ai_agent_cli.client_state import StoredSession
from ai_agent_cli.login import authorize_url, exchange_code, pkce_pair
from ai_agent_discord.store import Deployment, UserStore

_LOGIN_TTL = 600.0


@dataclass
class PendingLogin:
    discord_user_id: int
    server_url: str
    supabase_url: str
    anon_key: str
    verifier: str
    created: float


class LoginBroker:
    def __init__(
        self,
        store: UserStore,
        *,
        redirect_url: str,
        exchange=exchange_code,
    ):
        self.store = store
        self.redirect_url = redirect_url
        self._exchange = exchange
        self._pending: dict[str, PendingLogin] = {}
        self._lock = threading.Lock()

    def begin(self, discord_user_id: int, deployment: Deployment) -> str:
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(32)
        pending = PendingLogin(
            discord_user_id=discord_user_id,
            server_url=deployment.server_url,
            supabase_url=deployment.supabase_url,
            anon_key=deployment.supabase_publishable_key,
            verifier=verifier,
            created=time.time(),
        )
        with self._lock:
            self._drop_expired()
            self._pending[state] = pending
        return authorize_url(
            supabase_url=deployment.supabase_url,
            anon_key=deployment.supabase_publishable_key,
            redirect_to=self.redirect_url,
            challenge=challenge,
            state=state,
        )

    def complete(self, query: dict[str, list[str]]) -> str:
        error = _first(query, "error_description") or _first(query, "error")
        code = _first(query, "code")
        state = _first(query, "state")
        if error and not code:
            return f"Discord sign-in failed: {error}"
        if not code or not state:
            return "Discord sign-in did not return a code. Run /login again."
        pending = self._take(state)
        if pending is None:
            return "That sign-in link has expired. Run /login again."
        try:
            session = self._exchange(
                supabase_url=pending.supabase_url,
                anon_key=pending.anon_key,
                code=code,
                verifier=pending.verifier,
            )
        except httpx.HTTPError:
            return "Could not finish sign-in. Run /login again."
        if not isinstance(session, StoredSession):
            return "Could not finish sign-in. Run /login again."
        discord_id = discord_user_id_from_token(session.access_token)
        if discord_id != str(pending.discord_user_id):
            return (
                "That Discord account does not match the person who requested "
                "/login. Nothing was saved."
            )
        self.store.save_session(pending.discord_user_id, pending.server_url, session)
        return (
            f"Signed in to {pending.server_url}. "
            "You can close this window and return to Discord."
        )

    def _take(self, state: str) -> PendingLogin | None:
        with self._lock:
            self._drop_expired()
            return self._pending.pop(state, None)

    def _drop_expired(self) -> None:
        now = time.time()
        expired = [
            key for key, pending in self._pending.items() if now - pending.created >= _LOGIN_TTL
        ]
        for key in expired:
            self._pending.pop(key, None)


class OAuthServer:
    """HTTP listener for the Supabase redirect. Bind address and public URL differ."""

    def __init__(self, broker: LoginBroker, host: str, port: int):
        self.broker = broker
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._httpd = ThreadingHTTPServer((self.host, self.port), _handler(self.broker))
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="discord-oauth",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._httpd = None


def discord_user_id_from_token(access_token: str) -> str | None:
    """Discord snowflake carried in a Supabase access token.

    The token was just returned by Supabase's token endpoint, so this reads
    the payload to see who signed in. It does not treat the token as proof
    of anything else.
    """
    payload = _jwt_payload(access_token)
    if payload is None:
        return None
    meta = payload.get("user_metadata")
    if not isinstance(meta, dict):
        return None
    for key in ("provider_id", "sub"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip().isdigit():
            return value.strip()
    return None


def _jwt_payload(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return None
    segment = parts[1]
    pad = "=" * (-len(segment) % 4)
    try:
        data = base64.urlsafe_b64decode(segment + pad)
        payload = json.loads(data)
    except (ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or [""]
    return values[0] if values else ""


def _handler(broker: LoginBroker):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            message = broker.complete(parse_qs(parsed.query))
            body = message.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler
