from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)


def wait_for_upstream(
    base_url: str,
    path: str,
    *,
    timeout: float,
    poll_interval: float = 0.5,
) -> bool:
    """Poll an HTTP health endpoint until it responds or timeout elapses."""
    deadline = time.monotonic() + timeout
    url = f"{base_url.rstrip('/')}{path}"
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return True
        except httpx.HTTPError as exc:
            logger.debug("Upstream probe failed for %s: %s", url, exc)
        time.sleep(poll_interval)
    return False
