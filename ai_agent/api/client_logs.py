"""Client debug log upload.

Only accepted while the user has client_debug_logging on, because the lines can
contain what the user said to the agent.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import require_deployment_access
from ai_agent.api.settings import get_user_settings
from ai_agent.conversations.client_logs import ClientLogBatch, ClientLogError, ClientLogWriter
from ai_agent.conversations.user_settings import UserSettingsStore

router = APIRouter(tags=["client-logs"])

MAX_LINES = 1000
MAX_LINE_CHARS = 8000
DEBUG_OFF = "debug_logging_off"


class ClientLogBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: str = Field(min_length=1, max_length=64)
    device: str = Field(default="", max_length=200)
    first_seq: int = Field(ge=0)
    lines: list[str] = Field(max_length=MAX_LINES)


class ClientLogAck(BaseModel):
    next_seq: int


def get_client_log_writer(request: Request) -> ClientLogWriter:
    writer = getattr(request.app.state, "client_logs", None)
    if writer is None:
        raise HTTPException(status_code=503, detail="Client logs are not available.")
    return writer


@router.post("/api/me/client-logs", response_model=ClientLogAck)
def upload_client_logs(
    body: ClientLogBody,
    user: AuthenticatedUser = Depends(require_deployment_access),
    settings: UserSettingsStore = Depends(get_user_settings),
    writer: ClientLogWriter = Depends(get_client_log_writer),
) -> ClientLogAck:
    if not settings.get_preferences(user.user_id).client_debug_logging:
        raise HTTPException(
            status_code=403,
            detail={"code": DEBUG_OFF, "message": "Debug logging is off for this account."},
        )
    if any(len(line) > MAX_LINE_CHARS for line in body.lines):
        raise HTTPException(status_code=422, detail="A log line is too long.")
    batch = ClientLogBatch(
        stream=body.stream,
        device=body.device,
        first_seq=body.first_seq,
        lines=tuple(body.lines),
    )
    try:
        next_seq = writer.append(user.user_id, batch)
    except ClientLogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ClientLogAck(next_seq=next_seq)
