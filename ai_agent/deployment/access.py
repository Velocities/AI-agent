from __future__ import annotations

from enum import StrEnum

ACCESS_PENDING_CODE = "access_pending"
ACCESS_DENIED_CODE = "access_denied"

ACCESS_PENDING_MESSAGE = (
    "A whitelist request has been made for your account. You must wait for this "
    "to be approved before this deployment's agent functions for your account."
)
ACCESS_DENIED_MESSAGE = (
    "Access to this deployment was denied. Contact the server administrator if "
    "you believe this is a mistake."
)


class AccessStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
