from __future__ import annotations

from urllib.parse import urlparse


def parse_upstream_url(url: str) -> tuple[str, int]:
    """Return (host, port) from an http(s) upstream URL."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"LLM_UPSTREAM must be an http(s) URL, got {url!r}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"LLM_UPSTREAM is missing a host: {url!r}")
    if parsed.port is not None:
        return host, parsed.port
    return host, 443 if parsed.scheme == "https" else 80


def normalize_upstream_url(url: str) -> str:
    host, port = parse_upstream_url(url)
    return f"http://{host}:{port}"
