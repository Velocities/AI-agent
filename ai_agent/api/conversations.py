from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import get_current_user
from ai_agent.api.turns import iter_turn_events
from ai_agent.conversations.store import (
    Conversation,
    ConversationNotFound,
    ConversationStore,
    Message,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content is required")
        return value


class ApprovalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    grant_scope: str | None = None


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    metadata: dict
    position: int


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]


def get_store(request: Request) -> ConversationStore:
    store = request.app.state.store
    if store is None:
        raise HTTPException(status_code=503, detail="Conversation storage is not configured.")
    return store


@router.post("", response_model=ConversationResponse)
def create_conversation(
    body: CreateConversationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_store),
) -> ConversationResponse:
    conversation = store.create_conversation(user.user_id, title=body.title)
    return _conversation_response(conversation)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_store),
) -> ConversationListResponse:
    rows = store.list_conversations(user.user_id)
    return ConversationListResponse(conversations=[_conversation_response(row) for row in rows])


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_store),
) -> ConversationResponse:
    conversation = store.get_conversation(user.user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return _conversation_response(conversation)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_store),
) -> MessageListResponse:
    try:
        rows = store.list_messages(user.user_id, conversation_id)
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found.") from None
    return MessageListResponse(messages=[_message_response(row) for row in rows])


@router.post("/{conversation_id}/turns")
def start_turn(
    conversation_id: str,
    body: TurnRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_store),
) -> StreamingResponse:
    if store.get_conversation(user.user_id, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    broker = request.app.state.broker
    if not broker.try_begin(conversation_id):
        raise HTTPException(
            status_code=409,
            detail="A turn is already running for this conversation.",
        )
    generator = iter_turn_events(
        settings=request.app.state.settings,
        store=store,
        broker=broker,
        sessions=request.app.state.approval_sessions,
        user_id=user.user_id,
        conversation_id=conversation_id,
        content=body.content,
        agent_factory=request.app.state.agent_factory,
    )
    return StreamingResponse(
        generator,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{conversation_id}/approvals/{approval_id}")
def resolve_approval(
    conversation_id: str,
    approval_id: str,
    body: ApprovalBody,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, bool]:
    found = request.app.state.broker.resolve(
        user_id=user.user_id,
        conversation_id=conversation_id,
        approval_id=approval_id,
        approved=body.approved,
        grant_scope=body.grant_scope,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Approval not found.")
    return {"ok": True}


def _conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=_iso(conversation.created_at),
        updated_at=_iso(conversation.updated_at),
    )


def _message_response(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=_iso(message.created_at),
        metadata=message.metadata,
        position=message.position,
    )


def _iso(value: datetime) -> str:
    return value.isoformat()
