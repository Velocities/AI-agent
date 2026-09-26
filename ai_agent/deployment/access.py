from __future__ import annotations

from enum import StrEnum

ACCESS_PENDING_CODE = "access_pending"
ACCESS_DENIED_CODE = "access_denied"
ACCESS_INCOMPLETE_CODE = "access_incomplete"

ACCESS_PENDING_MESSAGE = (
    "A whitelist request has been made for your account. You must wait for this "
    "to be approved before this deployment's agent functions for your account."
)
ACCESS_DENIED_MESSAGE = (
    "Access to this deployment was denied. Contact the server administrator if "
    "you believe this is a mistake."
)
ACCESS_INCOMPLETE_MESSAGE = (
    "Your account is approved but not linked to a Linux user on this server. "
    "Ask the administrator to run: ai-agent config access approve <user_id> --run-as <linux_user>"
)


class AccessStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
