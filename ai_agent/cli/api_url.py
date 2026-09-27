from __future__ import annotations

from urllib.parse import urlparse

# Ports the API uses on loopback; they are not the public HTTPS port behind Cloudflare.
_LOCAL_API_PORTS = frozenset({8000, 8080, 8765})


def public_api_base_url_hint(api_base_url: str) -> str | None:
    """Warn when API_BASE_URL mixes HTTPS with a loopback origin port."""
    parsed = urlparse(api_base_url.strip())
    if parsed.scheme != "https":
        return None
    if parsed.port not in _LOCAL_API_PORTS:
        return None
    host = parsed.hostname or ""
    if host in {"127.0.0.1", "localhost", "::1"}:
        return None
    return (
        f"API_BASE_URL uses https on port {parsed.port}. Through Cloudflare Tunnel the "
        f"client should be https://{host} with no port (TLS on 443). Port {parsed.port} "
        "is only for http://127.0.0.1 on the server."
    )
