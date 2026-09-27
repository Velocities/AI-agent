from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from rich.console import Console

from ai_agent.cli.credentials import StoredSession, clear_session, save_session
from ai_agent.config import Settings

_LOGIN_TIMEOUT = 180.0


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(*, supabase_url: str, anon_key: str, redirect_to: str, challenge: str) -> str:
    base = supabase_url.strip().rstrip("/")
    query = urlencode(
        {
            "provider": "discord",
            "redirect_to": redirect_to,
            "code_challenge": challenge,
            "code_challenge_method": "s256",
            "response_type": "code",
            "apikey": anon_key,
        }
    )
    return f"{base}/auth/v1/authorize?{query}"


def redirect_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/callback"


def exchange_code(
    *,
    supabase_url: str,
    anon_key: str,
    code: str,
    verifier: str,
    client: httpx.Client | None = None,
) -> StoredSession:
    return _token_request(
        supabase_url=supabase_url,
        anon_key=anon_key,
        grant_type="pkce",
        body={"auth_code": code, "code_verifier": verifier},
        client=client,
    )


def refresh_session(
    *,
    supabase_url: str,
    anon_key: str,
    refresh_token: str,
    client: httpx.Client | None = None,
) -> StoredSession:
    return _token_request(
        supabase_url=supabase_url,
        anon_key=anon_key,
        grant_type="refresh_token",
        body={"refresh_token": refresh_token},
        client=client,
    )


def main(argv: list[str] | None = None) -> int:
    del argv
    console = Console()
    settings = Settings()
    if not settings.supabase_url.strip() or not settings.supabase_anon_key.strip():
        console.print(
            "[red]Set SUPABASE_URL and SUPABASE_ANON_KEY in .env before logging in.[/red]"
        )
        return 1
    port = settings.cli_oauth_port
    if port < 1 or port > 65535:
        console.print(f"[red]CLI_OAUTH_PORT is not a valid port: {port}[/red]")
        return 1

    verifier, challenge = pkce_pair()
    redirect = redirect_url(port)
    url = authorize_url(
        supabase_url=settings.supabase_url,
        anon_key=settings.supabase_anon_key,
        redirect_to=redirect,
        challenge=challenge,
    )
    box: dict[str, str] = {}
    try:
        server = _CallbackServer(("127.0.0.1", port), _handler(box))
    except OSError as exc:
        console.print(f"[red]Could not listen on 127.0.0.1:{port}:[/red] {exc}")
        return 1
    server.timeout = 0.5
    thread = threading.Thread(target=server.serve_until_done, daemon=True)
    thread.start()
    console.print("Opening the browser for Discord sign-in.")
    console.print(f"If it does not open, visit:\n{url}\n")
    console.print(
        f"[dim]Add {redirect} to the Supabase redirect allow list "
        "if this is the first CLI login.[/dim]"
    )
    webbrowser.open(url)
    thread.join(timeout=_LOGIN_TIMEOUT)
    server.done.set()
    thread.join(timeout=2)
    server.server_close()
    code = box.get("code", "")
    error = box.get("error", "")
    if error:
        console.print(f"[red]Discord sign-in failed:[/red] {error}")
        return 1
    if not code:
        console.print("[red]Timed out waiting for Discord sign-in.[/red]")
        return 1
    try:
        session = exchange_code(
            supabase_url=settings.supabase_url,
            anon_key=settings.supabase_anon_key,
            code=code,
            verifier=verifier,
        )
    except httpx.HTTPError as exc:
        console.print(f"[red]Could not finish sign-in:[/red] {exc}")
        return 1
    save_session(session)
    console.print("[green]Signed in.[/green] Start a chat with [bold]ai-agent[/bold].")
    return 0


def logout() -> int:
    clear_session()
    Console().print("Signed out.")
    return 0


def _token_request(
    *,
    supabase_url: str,
    anon_key: str,
    grant_type: str,
    body: dict,
    client: httpx.Client | None,
) -> StoredSession:
    base = supabase_url.strip().rstrip("/")
    owns_client = client is None
    http = client or httpx.Client(timeout=30)
    try:
        response = http.post(
            f"{base}/auth/v1/token?grant_type={grant_type}",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {anon_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            http.close()
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in", 3600)
    if not isinstance(access, str) or not isinstance(refresh, str):
        raise httpx.HTTPError("Supabase did not return a session.")
    if not isinstance(expires_in, (int, float)):
        expires_in = 3600
    return StoredSession(
        access_token=access,
        refresh_token=refresh,
        expires_at=time.time() + float(expires_in),
    )


class _CallbackServer(ThreadingHTTPServer):
    def __init__(self, address, handler) -> None:
        super().__init__(address, handler)
        self.done = threading.Event()

    def serve_until_done(self) -> None:
        while not self.done.is_set():
            self.handle_request()


def _handler(box: dict[str, str]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            query = parse_qs(parsed.query)
            code = query.get("code", [""])[0]
            error = query.get("error_description", query.get("error", [""]))[0]
            if code:
                box["code"] = code
            if error and not code:
                box["error"] = error
            body = b"You can close this window and return to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.server.done.set()  # type: ignore[attr-defined]

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler
