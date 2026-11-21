"""Readiness of one workflow conversation.

These values are the contract the CLI and the Android client display. The
strings are stable; clients match them exactly.
"""

from __future__ import annotations

from enum import StrEnum


class WorkflowStatus(StrEnum):
    IS_BUILDING = "is_building"
    IS_STARTING_UP = "is_starting_up"
    IS_READY = "is_ready"
    IS_FAILED = "is_failed"


WORKFLOW_STATUSES: tuple[WorkflowStatus, ...] = (
    WorkflowStatus.IS_BUILDING,
    WorkflowStatus.IS_STARTING_UP,
    WorkflowStatus.IS_READY,
    WorkflowStatus.IS_FAILED,
)

WORKFLOW_NOT_READY_CODE = "workflow_not_ready"
WORKFLOW_NOT_READY_STATUS = 409


def workflow_status_text(status: WorkflowStatus) -> str:
    """One line for a client that is waiting on this status."""
    if status is WorkflowStatus.IS_BUILDING:
        return "Building the workflow image. You can type. Sending waits until it is ready."
    if status is WorkflowStatus.IS_STARTING_UP:
        return "Starting the workflow. You can type. Sending waits until it is ready."
    if status is WorkflowStatus.IS_READY:
        return "Workflow ready. You can send your first message."
    if status is WorkflowStatus.IS_FAILED:
        return "The workflow failed to start. Sending stays off."
    return "The workflow is not ready yet."


def not_ready_message(status: WorkflowStatus, failure: str = "") -> str:
    """Body of the turn response while the workflow cannot take a message."""
    if status is WorkflowStatus.IS_BUILDING:
        return "The workflow is not ready yet. The image is still being built."
    if status is WorkflowStatus.IS_STARTING_UP:
        return "The workflow is not ready yet. It is still starting up."
    if status is WorkflowStatus.IS_FAILED:
        detail = failure.strip() or "It failed to start."
        return f"The workflow is not ready yet. {detail}"
    return "The workflow is not ready yet."
