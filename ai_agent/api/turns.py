from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator

from ai_agent.agent.loop import AgentCancelled
from ai_agent.api.approvals import ApprovalBroker, RemoteApprovalPrompter
from ai_agent.api.transcript import message_from_record, message_metadata, message_payload
from ai_agent.approval.session import ApprovalSession
from ai_agent.attachments.image import ImageHandler
from ai_agent.attachments.replay import select_replay_message_ids
from ai_agent.attachments.store import AttachmentNotFound
from ai_agent.attachments.types import Attachment, checksum_bytes
from ai_agent.config import Settings
from ai_agent.conversations.store import ConversationNotFound, ConversationStore, Message
from ai_agent.llm.client.types import ImageInput, LLMMessage
from ai_agent.speech.live import SPEECH_NOT_CONFIGURED, ReplySpeaker

logger = logging.getLogger(__name__)

AGENT_FACTORY_MISSING_MESSAGE = "Agent execution is not configured on this server."


class AgentFactoryNotConfigured(RuntimeError):
    """No agent factory was supplied for a turn.

    The factory is what binds a turn to the requesting user's approved Linux
    account. Without it the agent would run as the service account, so a turn
    with no factory must fail instead of falling back to an unmapped agent.
    """


def iter_turn_events(
    *,
    settings: Settings,
    store: ConversationStore,
    broker: ApprovalBroker,
    sessions: dict[str, ApprovalSession],
    user_id: str,
    conversation_id: str,
    content: str,
    agent_factory=None,
    speak: bool = False,
    speaker=None,
    images: list[ImageInput] | None = None,
    prior_history: list[Message] | None = None,
    stored_user: Message | None = None,
    attachment_catalog=None,
    attachment_cache=None,
) -> Iterator[str]:
    """Run one agent turn and yield NDJSON events.

    The caller must already have claimed `conversation_id` on the broker.
    """
    events: queue.Queue[dict | None] = queue.Queue()
    cancel = threading.Event()

    def emit(event: dict) -> None:
        events.put(event)

    def worker() -> None:
        try:
            _run_turn(
                settings=settings,
                store=store,
                broker=broker,
                sessions=sessions,
                user_id=user_id,
                conversation_id=conversation_id,
                content=content,
                emit=emit,
                cancel=cancel,
                agent_factory=agent_factory,
                speak=speak,
                speaker=speaker,
                images=images,
                prior_history=prior_history,
                stored_user=stored_user,
                attachment_catalog=attachment_catalog,
                attachment_cache=attachment_cache,
            )
        except AgentCancelled:
            emit({"type": "done", "message": "", "error": "cancelled"})
        except ConversationNotFound:
            emit({"type": "error", "message": "Conversation not found."})
        except Exception:
            logger.exception("Turn failed for conversation %s", conversation_id)
            emit({"type": "error", "message": "The turn failed."})
        finally:
            events.put(None)
            broker.finish(conversation_id)

    thread = threading.Thread(target=worker, name="agent-turn", daemon=True)
    thread.start()
    try:
        while True:
            try:
                event = events.get(timeout=0.25)
            except queue.Empty:
                continue
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=True) + "\n"
    finally:
        cancel.set()


def _run_turn(
    *,
    settings: Settings,
    store: ConversationStore,
    broker: ApprovalBroker,
    sessions: dict[str, ApprovalSession],
    user_id: str,
    conversation_id: str,
    content: str,
    emit,
    cancel: threading.Event,
    agent_factory,
    speak: bool = False,
    speaker=None,
    images: list[ImageInput] | None = None,
    prior_history: list[Message] | None = None,
    stored_user: Message | None = None,
    attachment_catalog=None,
    attachment_cache=None,
) -> None:
    session = sessions.setdefault(user_id, ApprovalSession())
    prompter = RemoteApprovalPrompter(
        settings.agent_confirmation_mode,
        session,
        broker,
        user_id=user_id,
        conversation_id=conversation_id,
        emit=emit,
        cancel=cancel,
        timeout=settings.agent_approval_timeout,
    )
    if agent_factory is None:
        raise AgentFactoryNotConfigured(AGENT_FACTORY_MISSING_MESSAGE)
    agent = agent_factory(
        settings=settings,
        prompter=prompter,
        session=session,
        audit_user=user_id,
    )
    try:
        _drive_agent(
            agent,
            settings=settings,
            store=store,
            user_id=user_id,
            conversation_id=conversation_id,
            content=content,
            emit=emit,
            cancel=cancel,
            speak=speak,
            speaker=speaker,
            images=images,
            prior_history=prior_history,
            stored_user=stored_user,
            attachment_catalog=attachment_catalog,
            attachment_cache=attachment_cache,
        )
    finally:
        llm = getattr(agent, "llm", None)
        close = getattr(llm, "close", None)
        if close is not None:
            close()


def _drive_agent(
    agent,
    *,
    settings: Settings,
    store: ConversationStore,
    user_id: str,
    conversation_id: str,
    content: str,
    emit,
    cancel: threading.Event,
    speak: bool = False,
    speaker=None,
    images: list[ImageInput] | None = None,
    prior_history: list[Message] | None = None,
    stored_user: Message | None = None,
    attachment_catalog=None,
    attachment_cache=None,
) -> None:
    reply_speaker = None
    if speak:
        if speaker is None:
            emit({"type": "audio", "error": SPEECH_NOT_CONFIGURED})
        else:
            reply_speaker = ReplySpeaker(speaker, emit, cancel)

    sent_stored_user = False

    def on_message(message) -> None:
        nonlocal sent_stored_user
        if stored_user is not None and not sent_stored_user and message.role == "user":
            sent_stored_user = True
            emit({"type": "message", "message": message_payload(stored_user)})
            return
        record = store.append_message(
            user_id,
            conversation_id,
            role=message.role,
            content=message.content or "",
            metadata=message_metadata(message),
        )
        emit({"type": "message", "message": message_payload(record)})

    agent.on_message = on_message
    agent.should_stop = cancel.is_set
    history = (
        store.list_messages(user_id, conversation_id)
        if prior_history is None
        else prior_history
    )
    chosen: set[str] = set()
    loader = None
    if attachment_catalog is not None and attachment_cache is not None:
        current = images or []
        chosen = select_replay_message_ids(
            history,
            current_images=len(current),
            current_bytes=sum(len(image.data) for image in current),
            max_messages=settings.attachment_replay_messages,
            max_images=settings.attachment_replay_max_images,
            max_bytes=settings.attachment_replay_max_bytes,
        )
        loader = _replay_loader(
            user_id,
            catalog=attachment_catalog,
            cache=attachment_cache,
        )
    for record in history:
        agent.messages.append(
            message_from_record(
                record,
                loader=loader,
                include_images=record.id in chosen,
            )
        )

    def on_token(text: str) -> None:
        if not text:
            return
        emit({"type": "token", "text": text})
        if reply_speaker is not None:
            reply_speaker.push(text)

    def on_notice(text: str) -> None:
        emit({"type": "notice", "text": text})

    def on_iteration(iteration: int) -> None:
        if iteration > 1:
            emit({"type": "status", "text": f"Working (step {iteration})"})

    try:
        result = agent.run(
            content,
            stream_callback=on_token,
            notice_callback=on_notice,
            iteration_callback=on_iteration,
            images=images,
        )
    finally:
        if reply_speaker is not None:
            reply_speaker.finish()
    emit(
        {
            "type": "done",
            "message": result.final_message,
            "error": result.error,
        }
    )


def persist_user_turn(
    *,
    store: ConversationStore,
    catalog,
    user_id: str,
    conversation_id: str,
    refs: list[Attachment],
    message: LLMMessage,
) -> Message:
    """Insert catalog rows and the user message in one transaction."""
    from sqlalchemy.orm import Session

    with Session(store.engine) as db:
        for ref in refs:
            catalog.insert(db, ref)
        saved = store.append_message_in(
            db,
            user_id,
            conversation_id,
            role=message.role,
            content=message.content or "",
            metadata=message_metadata(message),
        )
        db.commit()
        return saved


def _replay_loader(user_id: str, *, catalog, cache):
    """Load each image attachment at most once per turn."""
    handler = ImageHandler()
    memo: dict[str, ImageInput | None] = {}

    def load(attachment_id: str) -> ImageInput | None:
        if attachment_id in memo:
            return memo[attachment_id]
        attachment = catalog.get(user_id, attachment_id)
        if attachment is None or attachment.kind != "image":
            if attachment is None:
                logger.warning(
                    "Attachment %s is missing; omitting it from the turn",
                    attachment_id,
                )
            memo[attachment_id] = None
            return None
        try:
            data = _read_attachment(cache, attachment)
        except AttachmentNotFound:
            logger.warning(
                "Attachment %s is missing; omitting it from the turn",
                attachment_id,
            )
            memo[attachment_id] = None
            return None
        image = handler.to_model(attachment, data)
        memo[attachment_id] = image
        return image

    return load


def _read_attachment(cache, attachment: Attachment) -> bytes:
    getter = cache.get
    try:
        return getter(
            attachment.user_id,
            attachment.id,
            checksum=attachment.checksum,
        )
    except TypeError:
        return attachment.load_bytes(cache)


def attachment_from_image(
    *,
    user_id: str,
    conversation_id: str,
    image: ImageInput,
    kind: str = "image",
) -> Attachment:
    if not image.attachment_id:
        raise ValueError("attachment id is required")
    return Attachment(
        id=image.attachment_id,
        user_id=user_id,
        conversation_id=conversation_id,
        kind=kind,
        media_type=image.media_type,
        byte_size=len(image.data),
        checksum=checksum_bytes(image.data),
    )
