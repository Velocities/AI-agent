"""Build a workflow image when it is missing, then start its container.

The image is identified by the closure tag. A tag that is already present is
not built again. Prepare runs off the request thread so the client can show
the status and keep a draft while sending stays closed.
"""

from __future__ import annotations

import logging
import platform
import subprocess
import threading
from collections.abc import Callable

from ai_agent.workflows.image_supply import WorkflowImageCache, broker_workflow_image_supply
from ai_agent.workflows.manifests import default_sandbox_root
from ai_agent.workflows.runtime import (
    WorkflowAttachment,
    WorkflowRuntimeError,
    ensure_workflow_container,
    open_attached_workflow,
)
from ai_agent.workflows.session import WorkflowSession
from ai_agent.workflows.status import WorkflowStatus

logger = logging.getLogger(__name__)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
Spawn = Callable[..., None]


class ManualWorkflowLifecycle:
    """In-memory machine a test can move with set_status. It never calls Docker."""

    def __init__(self) -> None:
        self._status: dict[str, WorkflowStatus] = {}
        self._failures: dict[str, str] = {}
        self.begun: list[tuple[WorkflowAttachment, str]] = []
        self._lock = threading.Lock()

    def set_status(self, conversation_id: str, status: WorkflowStatus) -> None:
        with self._lock:
            self._status[conversation_id] = status

    def set_failure(self, conversation_id: str, message: str) -> None:
        with self._lock:
            self._status[conversation_id] = WorkflowStatus.IS_FAILED
            self._failures[conversation_id] = message

    def status(self, conversation_id: str) -> WorkflowStatus | None:
        with self._lock:
            return self._status.get(conversation_id)

    def failure(self, conversation_id: str) -> str:
        with self._lock:
            return self._failures.get(conversation_id, "")

    def begin(self, attachment: WorkflowAttachment, linux_username: str) -> WorkflowStatus:
        with self._lock:
            self.begun.append((attachment, linux_username))
            current = self._status.get(attachment.conversation_id)
            if current is None:
                current = WorkflowStatus.IS_BUILDING
                self._status[attachment.conversation_id] = current
            return current

    def forget(self, conversation_id: str) -> None:
        with self._lock:
            self._status.pop(conversation_id, None)
            self._failures.pop(conversation_id, None)


class DockerWorkflowLifecycle:
    """The process-wide machine used by the API."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        start_container: Callable[[WorkflowSession], None] | None = None,
        spawn: Spawn | None = None,
        sandbox_root=None,
        nix_system: str | None = None,
    ) -> None:
        self._runner = runner or _subprocess_runner
        self._start_container = start_container or ensure_workflow_container
        self._spawn = spawn or _spawn_thread
        self._sandbox_root = sandbox_root or default_sandbox_root()
        self._nix_system = nix_system or _nix_system()
        self._image_cache = WorkflowImageCache(
            broker_workflow_image_supply(self._runner),
            sandbox_root=self._sandbox_root,
            nix_system=self._nix_system,
        )
        self._status: dict[str, WorkflowStatus] = {}
        self._failures: dict[str, str] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def status(self, conversation_id: str) -> WorkflowStatus | None:
        with self._lock:
            return self._status.get(conversation_id)

    def failure(self, conversation_id: str) -> str:
        with self._lock:
            return self._failures.get(conversation_id, "")

    def begin(self, attachment: WorkflowAttachment, linux_username: str) -> WorkflowStatus:
        """Record the first status and prepare in the background.

        Binding the session happens before a status is published, so a bad
        manifest does not leave the chat stuck in "building".
        """
        conversation_id = attachment.conversation_id
        with self._lock:
            current = self._status.get(conversation_id)
            if current in {
                WorkflowStatus.IS_BUILDING,
                WorkflowStatus.IS_STARTING_UP,
                WorkflowStatus.IS_READY,
            }:
                return current
        session = open_attached_workflow(
            attachment,
            linux_username,
            sandbox_root=self._sandbox_root,
        )
        image = self._image_cache.inspect_session(session)
        if image.unavailable:
            self._fail(conversation_id, image.unavailable)
            return WorkflowStatus.IS_FAILED
        initial = (
            WorkflowStatus.IS_STARTING_UP if image.present else WorkflowStatus.IS_BUILDING
        )
        with self._lock:
            current = self._status.get(conversation_id)
            if current in {
                WorkflowStatus.IS_BUILDING,
                WorkflowStatus.IS_STARTING_UP,
                WorkflowStatus.IS_READY,
            }:
                return current
            self._cancelled.discard(conversation_id)
            self._status[conversation_id] = initial
        logger.info(
            "Workflow %s for conversation %s is %s (image %s)",
            session.manifest.name,
            conversation_id,
            initial.value,
            session.image,
        )
        self._spawn(self._prepare, (conversation_id, session, image.present))
        return self.status(conversation_id) or initial

    def forget(self, conversation_id: str) -> None:
        with self._lock:
            self._cancelled.add(conversation_id)
            self._status.pop(conversation_id, None)
            self._failures.pop(conversation_id, None)

    def _prepare(
        self,
        conversation_id: str,
        session: WorkflowSession,
        image_present: bool,
    ) -> None:
        try:
            if self._is_cancelled(conversation_id):
                return
            if not image_present:
                self._set(conversation_id, WorkflowStatus.IS_BUILDING)
                self._image_cache.build_session(session)
            if self._is_cancelled(conversation_id):
                return
            self._set(conversation_id, WorkflowStatus.IS_STARTING_UP)
            logger.info(
                "Starting workflow container %s from %s",
                session.container_name,
                session.image,
            )
            self._start_container(session)
            if self._is_cancelled(conversation_id):
                return
            self._set(conversation_id, WorkflowStatus.IS_READY)
            logger.info("Workflow container %s is ready", session.container_name)
        except Exception as exc:
            if self._is_cancelled(conversation_id):
                return
            logger.exception(
                "Workflow %s failed while preparing image %s",
                conversation_id,
                session.image,
            )
            self._fail(conversation_id, str(exc))

    def _set(self, conversation_id: str, status: WorkflowStatus) -> None:
        with self._lock:
            if conversation_id in self._cancelled:
                return
            self._status[conversation_id] = status

    def _is_cancelled(self, conversation_id: str) -> bool:
        with self._lock:
            return conversation_id in self._cancelled

    def _fail(self, conversation_id: str, message: str) -> None:
        text = message.strip() or "It failed to start."
        with self._lock:
            if conversation_id in self._cancelled:
                return
            self._failures[conversation_id] = text
            self._status[conversation_id] = WorkflowStatus.IS_FAILED
        logger.error("Workflow %s failed: %s", conversation_id, text)


def _spawn_thread(target, args) -> None:
    threading.Thread(
        target=target,
        args=args,
        name="workflow-prepare",
        daemon=True,
    ).start()


def _subprocess_runner(argv, *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Ask the Docker broker to run an already-built workflow argv.

    The broker authorizes the argv again and is the process that opens the
    Docker socket. This function does not run Docker itself.
    """
    from ai_agent.docker_broker.client import default_docker_broker

    logger.info("Asking the Docker broker to run: %s", " ".join(argv))
    return default_docker_broker().invoke(argv, timeout=timeout)


def _nix_system() -> str:
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        return "aarch64-linux"
    return "x86_64-linux"
