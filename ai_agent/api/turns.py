from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator

from ai_agent.agent.loop import AgentCancelled, AgentLoop
from ai_agent.api.approvals import ApprovalBroker, RemoteApprovalPrompter
from ai_agent.api.transcript import message_from_record, message_metadata
from ai_agent.approval.session import ApprovalSession
from ai_agent.cli.app import build_agent
from ai_agent.config import Settings
from ai_agent.conversations.store import ConversationNotFound, ConversationStore

logger = logging.getLogger(__name__)


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
    factory = agent_factory or _default_agent_factory
    agent = factory(
        settings=settings,
        prompter=prompter,
        session=session,
        audit_user=user_id,
    )
    try:
        _drive_agent(
            agent,
            store=store,
            user_id=user_id,
            conversation_id=conversation_id,
            content=content,
            emit=emit,
            cancel=cancel,
        )
    finally:
        llm = getattr(agent, "llm", None)
        close = getattr(llm, "close", None)
        if close is not None:
            close()


def _drive_agent(
    agent,
    *,
    store: ConversationStore,
    user_id: str,
    conversation_id: str,
    content: str,
    emit,
    cancel: threading.Event,
) -> None:
    agent.on_message = lambda message: store.append_message(
        user_id,
        conversation_id,
        role=message.role,
        content=message.content or "",
        metadata=message_metadata(message),
    )
    agent.should_stop = cancel.is_set
    history = store.list_messages(user_id, conversation_id)
    for record in history:
        agent.messages.append(message_from_record(record))

    def on_token(text: str) -> None:
        if text:
            emit({"type": "token", "text": text})

    def on_notice(text: str) -> None:
        emit({"type": "notice", "text": text})

    def on_iteration(iteration: int) -> None:
        if iteration > 1:
            emit({"type": "status", "text": f"Working (step {iteration})"})

    result = agent.run(
        content,
        stream_callback=on_token,
        notice_callback=on_notice,
        iteration_callback=on_iteration,
    )
    emit(
        {
            "type": "done",
            "message": result.final_message,
            "error": result.error,
        }
    )


def _default_agent_factory(
    *,
    settings: Settings,
    prompter,
    session,
    audit_user: str,
) -> AgentLoop:
    return build_agent(
        prompter=prompter,
        session=session,
        audit_user=audit_user,
        settings=settings,
    )
