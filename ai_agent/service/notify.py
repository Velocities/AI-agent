from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger(__name__)


def sd_notify(status: str, *, ready: bool = False, stopping: bool = False) -> None:
    """Tell systemd the service state when NOTIFY_SOCKET is set.

    No-op outside systemd. A failed notification is logged and does not abort
    the process; Type=notify will still time out if READY=1 never arrives.
    """
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]

    fields: list[str] = []
    if ready:
        fields.append("READY=1")
    if stopping:
        fields.append("STOPPING=1")
    clean = " ".join(status.split())
    if clean:
        fields.append(f"STATUS={clean}")
    if not fields:
        return

    payload = ("\n".join(fields) + "\n").encode()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.sendto(payload, address)
    except OSError:
        logger.warning("Could not notify systemd at NOTIFY_SOCKET", exc_info=True)
    finally:
        sock.close()
