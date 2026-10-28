from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import require_deployment_access
from ai_agent.api.speech import load_text_to_speech
from ai_agent.api.turns import (
    AGENT_FACTORY_MISSING_MESSAGE,
    attachment_from_image,
    iter_turn_events,
    persist_user_turn,
)
from ai_agent.approval.selection import InvalidApprovalDecision
from ai_agent.attachments import select_handler
from ai_agent.attachments.image import ImageHandler
from ai_agent.attachments.store import AttachmentNotFound, AttachmentQuotaExceeded
from ai_agent.attachments.types import ValidatedUpload
from ai_agent.conversations.store import (
    Conversation,
    ConversationNotFound,
    ConversationStore,
    Message,
)
from ai_agent.images import ImageRejected, validate_image_bytes
from ai_agent.llm.client.types import ImageInput, LLMMessage

logger = logging.getLogger(__name__)

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


class CommandDecisionBody(BaseModel):
    """One command in a batch, numbered from 1 in the approval event."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    decision: Literal["accept", "reject"]


class ApprovalBody(BaseModel):
    """Approve or reject a whole batch, or send a decision for every command.

    `approved` is the existing all-or-nothing choice. `decisions` lets the
    client accept some commands and reject others. A session grant only applies
    when the whole batch is approved.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool | None = None
    grant_scope: str | None = None
    decisions: list[CommandDecisionBody] | None = None

    @model_validator(mode="after")
    def require_one_choice(self) -> Self:
        if self.decisions:
            if self.approved is not None:
                raise ValueError("Omit approved when sending per-command decisions.")
            if self.grant_scope is not None:
                raise ValueError("A session grant applies only when every command is approved.")
            return self
        if self.approved is None:
            raise ValueError("approved is required")
        return self


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
        removed = store.delete_conversation(
            user.user_id,
            conversation_id,
            catalog=getattr(request.app.state, "attachment_catalog", None),
        )
        if not removed:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        blobs = getattr(request.app.state, "attachment_store", None)
        if blobs is not None:
            try:
                blobs.delete_conversation(user.user_id, conversation_id)
            except Exception:
                logger.exception(
                    "Could not delete attachment files for conversation %s",
                    conversation_id,
                )
        cache = getattr(request.app.state, "attachment_cache", None)
        if cache is not None:
            cache.invalidate_conversation(user.user_id, conversation_id)
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
    validated, optionally stripped, and stored before the agent runs.
    """
    content, images, speak = await _read_turn_input(request)
    if store.get_conversation(user.user_id, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if images:
        images = _prepare_images(request, user.user_id, images)
    # Checked before claiming the broker so a refused turn leaves the
    # conversation free rather than permanently busy.
    if request.app.state.agent_factory is None:
        raise HTTPException(status_code=503, detail=AGENT_FACTORY_MISSING_MESSAGE)
    if images and getattr(request.app.state, "attachment_store", None) is None:
        raise HTTPException(status_code=503, detail="Attachment storage is not configured.")
    broker = request.app.state.broker
    if not broker.try_begin(conversation_id):
        raise HTTPException(
            status_code=409,
            detail="A turn is already running for this conversation.",
        )
    prior_history = None
    stored_user = None
    try:
        if images:
            prior_history = store.list_messages(user.user_id, conversation_id)
            images, stored_user = _commit_images(
                request,
                store,
                user_id=user.user_id,
                conversation_id=conversation_id,
                content=content,
                images=images,
            )
    except HTTPException:
        broker.finish(conversation_id)
        raise
    except Exception:
        logger.exception("Could not store images for conversation %s", conversation_id)
        broker.finish(conversation_id)
        raise HTTPException(status_code=500, detail="The turn failed.") from None
    speaker = load_text_to_speech(request) if speak else None
    pronunciations = _speech_pronunciations(request, user.user_id) if speak else ()
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
        prior_history=prior_history,
        stored_user=stored_user,
        attachment_catalog=getattr(request.app.state, "attachment_catalog", None),
        attachment_cache=getattr(request.app.state, "attachment_cache", None),
        pronunciations=pronunciations,
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
    decisions = (
        [(item.id, item.decision) for item in body.decisions] if body.decisions else None
    )
    try:
        found = request.app.state.broker.resolve(
            user_id=user.user_id,
            conversation_id=conversation_id,
            approval_id=approval_id,
            approved=bool(body.approved),
            grant_scope=body.grant_scope,
            decisions=decisions,
        )
    except InvalidApprovalDecision as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
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
        settings = request.app.state.settings
        uploads = form.getlist("images")
        if uploads and not _vision_enabled(request):
            raise HTTPException(status_code=400, detail="This model does not accept images.")
        if len(uploads) > settings.image_max_count:
            raise HTTPException(
                status_code=400,
                detail=f"Too many images (max {settings.image_max_count}).",
            )
        images: list[ImageInput] = []
        for item in uploads:
            if not hasattr(item, "read"):
                raise HTTPException(status_code=400, detail="Invalid image upload.")
            data = await item.read(settings.image_max_bytes + 1)
            declared = getattr(item, "content_type", None)
            declared_type = declared if isinstance(declared, str) else None
            try:
                selected = select_handler(data, declared_type)
                if selected is None:
                    validate_image_bytes(
                        data,
                        declared_type=declared_type,
                        max_bytes=settings.image_max_bytes,
                        max_pixels=settings.image_max_pixels,
                        max_dimension=settings.image_max_dimension,
                    )
                    raise HTTPException(status_code=400, detail="Invalid image data.")
                upload = selected.validate(
                    data,
                    settings=settings,
                    declared_type=declared_type,
                )
            except ImageRejected as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
            images.append(ImageInput(data=upload.data, media_type=upload.media_type))
        if len(images) > settings.attachment_replay_max_images:
            raise HTTPException(
                status_code=400,
                detail=f"Too many images (max {settings.attachment_replay_max_images}).",
            )
        if sum(len(image.data) for image in images) > settings.attachment_replay_max_bytes:
            raise HTTPException(status_code=413, detail="Images exceed the per-turn size limit.")
        if not content.strip() and not images:
            raise HTTPException(status_code=400, detail="content is required")
        return content, images, speak
    finally:
        await form.close()


def _vision_enabled(request: Request) -> bool:
    info = getattr(request.app.state, "model_info", None)
    return bool(info is not None and info.vision)


def _speech_pronunciations(request: Request, user_id: str) -> tuple[tuple[str, str], ...]:
    """Written names to swap for respellings before Kokoro. Empty when unset."""
    store = getattr(request.app.state, "user_settings", None)
    if store is None:
        return ()
    return store.get_preferences(user_id).speech_pairs()


def _prepare_images(request: Request, user_id: str, images: list[ImageInput]) -> list[ImageInput]:
    settings = request.app.state.settings
    handler = ImageHandler()
    user_settings = getattr(request.app.state, "user_settings", None)
    prepared: list[ImageInput] = []
    for image in images:
        try:
            ready = handler.prepare(
                ValidatedUpload(data=image.data, media_type=image.media_type, kind=handler.kind),
                user_settings=user_settings,
                user_id=user_id,
            )
        except ImageRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        prepared.append(ImageInput(data=ready.data, media_type=ready.media_type))
    if len(prepared) > settings.attachment_replay_max_images:
        raise HTTPException(
            status_code=400,
            detail=f"Too many images (max {settings.attachment_replay_max_images}).",
        )
    if sum(len(image.data) for image in prepared) > settings.attachment_replay_max_bytes:
        raise HTTPException(status_code=413, detail="Images exceed the per-turn size limit.")
    return prepared


def _commit_images(
    request: Request,
    store: ConversationStore,
    *,
    user_id: str,
    conversation_id: str,
    content: str,
    images: list[ImageInput],
) -> tuple[list[ImageInput], Message]:
    blobs = request.app.state.attachment_store
    catalog = request.app.state.attachment_catalog
    cache = getattr(request.app.state, "attachment_cache", None)
    stored_ids: list[str] = []
    try:
        stamped: list[ImageInput] = []
        for image in images:
            attachment_id = blobs.put(
                user_id,
                conversation_id,
                media_type=image.media_type,
                data=image.data,
            )
            stored_ids.append(attachment_id)
            stamped.append(
                ImageInput(
                    data=image.data,
                    media_type=image.media_type,
                    attachment_id=attachment_id,
                )
            )
        message = LLMMessage(role="user", content=content, images=stamped)
        refs = [
            attachment_from_image(
                user_id=user_id,
                conversation_id=conversation_id,
                image=image,
            )
            for image in stamped
        ]
        record = persist_user_turn(
            store=store,
            catalog=catalog,
            user_id=user_id,
            conversation_id=conversation_id,
            refs=refs,
            message=message,
        )
        return stamped, record
    except AttachmentQuotaExceeded as exc:
        _compensate(blobs, cache, user_id, stored_ids)
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except (AttachmentNotFound, OSError, ImageRejected) as exc:
        _compensate(blobs, cache, user_id, stored_ids)
        logger.exception("Attachment write failed")
        status = getattr(exc, "status_code", 500)
        raise HTTPException(status_code=status, detail="The turn failed.") from None
    except Exception:
        _compensate(blobs, cache, user_id, stored_ids)
        raise


def _compensate(blobs, cache, user_id: str, attachment_ids: list[str]) -> None:
    for attachment_id in attachment_ids:
        try:
            blobs.delete(user_id, attachment_id)
        except AttachmentNotFound:
            continue
        except Exception:
            logger.exception("Could not compensate attachment %s", attachment_id)
        if cache is not None:
            cache.invalidate(user_id, attachment_id)


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
