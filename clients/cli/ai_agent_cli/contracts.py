"""HTTP API contract literals shared with the Android client (keep in sync)."""

from __future__ import annotations

from enum import StrEnum

CLIENT_CONFIG_PATH = "/api/client-config"

DEFAULT_LOCAL_STANDALONE_USER_ID = "00000000-0000-4000-8000-000000000001"

ACCESS_PENDING_CODE = "access_pending"
ACCESS_DENIED_CODE = "access_denied"
ACCESS_INCOMPLETE_CODE = "access_incomplete"


class WorkflowStatus(StrEnum):
    IS_BUILDING = "is_building"
    IS_STARTING_UP = "is_starting_up"
    IS_READY = "is_ready"
    IS_FAILED = "is_failed"


def workflow_status_text(status: WorkflowStatus) -> str:
    if status is WorkflowStatus.IS_BUILDING:
        return "Building the workflow image. You can type. Sending waits until it is ready."
    if status is WorkflowStatus.IS_STARTING_UP:
        return "Starting the workflow. You can type. Sending waits until it is ready."
    if status is WorkflowStatus.IS_READY:
        return "Workflow ready. You can send your first message."
    if status is WorkflowStatus.IS_FAILED:
        return "The workflow failed to start. Sending stays off."
    return "The workflow is not ready yet."