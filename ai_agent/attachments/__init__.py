"""Conversation attachment records, handlers, and the store protocol.

Agent and API code import these names. The on-disk store is constructed by
`open_attachment_services` and is not the default import.
"""

from ai_agent.attachments.handlers import HANDLERS, AttachmentHandler, select_handler
from ai_agent.attachments.store import (
    AttachmentError,
    AttachmentNotFound,
    AttachmentQuotaExceeded,
    AttachmentRejected,
    AttachmentStore,
)
from ai_agent.attachments.types import Attachment, ValidatedUpload

__all__ = [
    "HANDLERS",
    "Attachment",
    "AttachmentError",
    "AttachmentHandler",
    "AttachmentNotFound",
    "AttachmentQuotaExceeded",
    "AttachmentRejected",
    "AttachmentStore",
    "ValidatedUpload",
    "select_handler",
]
