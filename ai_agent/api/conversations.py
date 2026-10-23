from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import require_deployment_access
from ai_agent.api.speech import load_text_to_speech
from ai_agent.api.turns import AGENT_FACTORY_MISSING_MESSAGE, iter_turn_events
from ai_agent.conversations.store import (
    Conversation,
    ConversationNotFound,
    ConversationStore,
    Message,
)
from ai_agent.images import ImageRejected, validate_image_bytes
from ai_agent.llm.client.types import ImageInput

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    speak: bool = False

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
    user: AuthenticatedUser = Depends(require_deployment_access),
    store: ConversationStore = Depends(get_store),
) -> ConversationResponse:
    conversation = store.create_conversation(user.user_id, title=body.title)
    return _conversation_response(conversation)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    user: AuthenticatedUser = Depends(require_deployment_access),
    store: ConversationStore = Depends(get_store),
) -> ConversationListResponse:
    rows = store.list_conversations(user.user_id)
    return ConversationListResponse(conversations=[_conversation_response(row) for row in rows])


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(require_deployment_access),
    store: ConversationStore = Depends(get_store),
) -> ConversationResponse:
    conversation = store.get_conversation(user.user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return _conversation_response(conversation)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_deployment_access),
    store: ConversationStore = Depends(get_store),
) -> Response:
    if store.get_conversation(user.user_id, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    broker = request.app.state.broker
    if not broker.try_begin(conversation_id):
        raise HTTPException(
            status_code=409,
            detail="A turn is running in this conversation. Stop it before deleting.",
        )
    try:
        store.delete_conversation(user.user_id, conversation_id)
    finally:
        broker.finish(conversation_id)
    return Response(status_code=204)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: str,
    user: AuthenticatedUser = Depends(require_deployment_access),
    store: ConversationStore = Depends(get_store),
) -> MessageListResponse:
    try:
        rows = store.list_messages(user.user_id, conversation_id)
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found.") from None
    return MessageListResponse(messages=[_message_response(row) for row in rows])


@router.post("/{conversation_id}/turns")
async def start_turn(
    conversation_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_deployment_access),
    store: ConversationStore = Depends(get_store),
) -> StreamingResponse:
    """Start a turn from JSON or from a multipart upload.

    JSON is ``{"content": "...", "speak": false}``. Multipart uses a
    ``content`` field and zero or more ``images`` files. Image bytes are
    validated here and passed to the agent as ``ImageInput``. They are not
    written into the stored transcript.
    """
    content, images, speak = await _read_turn_input(request)
    if store.get_conversation(user.user_id, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    # Checked before claiming the broker so a refused turn leaves the
    # conversation free rather than permanently busy.
    if request.app.state.agent_factory is None:
        raise HTTPException(status_code=503, detail=AGENT_FACTORY_MISSING_MESSAGE)
    broker = request.app.state.broker
    if not broker.try_begin(conversation_id):
        raise HTTPException(
            status_code=409,
            detail="A turn is already running for this conversation.",
        )
    speaker = load_text_to_speech(request) if speak else None
    generator = iter_turn_events(
        settings=request.app.state.settings,
        store=store,
        broker=broker,
        sessions=request.app.state.approval_sessions,
        user_id=user.user_id,
        conversation_id=conversation_id,
        content=content,
        agent_factory=request.app.state.agent_factory,
        speak=speak,
        speaker=speaker,
        images=images,
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
    user: AuthenticatedUser = Depends(require_deployment_access),
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


async def _read_turn_input(request: Request) -> tuple[str, list[ImageInput], bool]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        return await _read_multipart_turn(request)
    return await _read_json_turn(request)


async def _read_json_turn(request: Request) -> tuple[str, list[ImageInput], bool]:
    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Request body must be JSON.") from None
    try:
        body = TurnRequest.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from None
    return body.content, [], body.speak


async def _read_multipart_turn(request: Request) -> tuple[str, list[ImageInput], bool]:
    form = await request.form()
    try:
        raw_content = form.get("content")
        content = raw_content if isinstance(raw_content, str) else ""
        speak = _form_flag(form.get("speak"))
        max_bytes = request.app.state.settings.image_max_bytes
        images: list[ImageInput] = []
        for item in form.getlist("images"):
            if not hasattr(item, "read"):
                raise HTTPException(status_code=400, detail="Invalid image upload.")
            data = await item.read(max_bytes + 1)
            declared = getattr(item, "content_type", None)
            try:
                images.append(
                    validate_image_bytes(
                        data,
                        declared_type=declared if isinstance(declared, str) else None,
                        max_bytes=max_bytes,
                    )
                )
            except ImageRejected as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        if not content.strip() and not images:
            raise HTTPException(status_code=400, detail="content is required")
        return content, images, speak
    finally:
        await form.close()


def _form_flag(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
