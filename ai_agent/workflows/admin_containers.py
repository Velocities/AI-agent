"""List and remove workflow Docker containers for deployment admins.

Workflow containers use names ``wf`` + up to 32 lowercase hex digits (from the
conversation id). These helpers only touch containers that match that pattern.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ai_agent.workflows.runtime import container_name_for

WORKFLOW_CONTAINER_NAME = re.compile(r"^wf[0-9a-f]{8,32}$")

StateFilter = Literal["all", "running", "stopped", "dead"]

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class WorkflowContainer:
    name: str
    container_id: str
    image: str
    state: str
    status: str
    created: str
    conversation_id_hint: str = ""
    chat_title: str = ""
    workflow_name: str = ""

    @property
    def state_label(self) -> str:
        """Short label for tables: running, exited, dead, …"""
        lowered = self.state.lower()
        if lowered == "dead":
            return "dead"
        if lowered == "running":
            return "running"
        if lowered in {"exited", "created", "paused", "restarting", "removing"}:
            return lowered
        return lowered or "unknown"


def default_docker_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the ``docker`` CLI on the host (admin shell, not the API broker)."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def list_workflow_containers(
    *,
    runner: CommandRunner | None = None,
    state: StateFilter = "all",
) -> list[WorkflowContainer]:
    """Return workflow containers in name order."""
    run = runner or default_docker_runner
    result = run(
        [
            "docker",
            "ps",
            "-a",
            "--no-trunc",
            "--format",
            "{{json .}}",
        ]
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "docker ps failed").strip()
        raise RuntimeError(detail)
    rows: list[WorkflowContainer] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        name = _container_name(payload.get("Names", ""))
        if name is None:
            continue
        item = WorkflowContainer(
            name=name,
            container_id=str(payload.get("ID", "")),
            image=str(payload.get("Image", "")),
            state=str(payload.get("State", "")),
            status=str(payload.get("Status", "")),
            created=str(payload.get("CreatedAt", "")),
        )
        if not _state_matches(item, state):
            continue
        rows.append(item)
    rows.sort(key=lambda row: row.name)
    return rows


def remove_workflow_containers(
    names: list[str],
    *,
    runner: CommandRunner | None = None,
    all_workflows: bool = False,
    state: StateFilter = "all",
    containers: list[WorkflowContainer] | None = None,
) -> list[str]:
    """Remove containers by name. Returns names that were removed."""
    run = runner or default_docker_runner
    if all_workflows:
        pool = containers or list_workflow_containers(runner=run, state=state)
        targets = [item.name for item in pool]
    else:
        targets = []
        for raw in names:
            name = raw.removeprefix("/").strip()
            if not WORKFLOW_CONTAINER_NAME.fullmatch(name):
                raise ValueError(
                    f"{name!r} is not a workflow container name (expected wf + hex)."
                )
            targets.append(name)
    if not targets:
        return []
    argv = ["docker", "rm", "-f", *targets]
    result = run(argv)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "docker rm failed").strip()
        raise RuntimeError(detail)
    return targets


def attach_conversation_hints(
    rows: list[WorkflowContainer],
    *,
    engine,
) -> list[WorkflowContainer]:
    """Fill chat_title, workflow_name, and conversation_id_hint from SQLite."""
    from sqlalchemy.orm import sessionmaker

    index = _conversation_index(sessionmaker(bind=engine))
    enriched: list[WorkflowContainer] = []
    for row in rows:
        hint = index.get(row.name)
        if hint is None:
            enriched.append(row)
            continue
        conv_id, title, workflow = hint
        enriched.append(
            WorkflowContainer(
                name=row.name,
                container_id=row.container_id,
                image=row.image,
                state=row.state,
                status=row.status,
                created=row.created,
                conversation_id_hint=conv_id,
                chat_title=title,
                workflow_name=workflow,
            )
        )
    return enriched


def _conversation_index(session_factory) -> dict[str, tuple[str, str, str]]:
    from sqlalchemy import select

    from ai_agent.conversations.models import ConversationRow

    mapping: dict[str, tuple[str, str, str]] = {}
    with session_factory() as db:
        rows = db.scalars(
            select(ConversationRow).where(ConversationRow.workflow_name.is_not(None))
        ).all()
        for row in rows:
            if not row.workflow_name:
                continue
            name = container_name_for(row.id)
            title = (row.title or "").strip()
            mapping[name] = (row.id, title, row.workflow_name)
    return mapping


def _container_name(names_field: object) -> str | None:
    if not isinstance(names_field, str):
        return None
    primary = names_field.split(",")[0].strip().removeprefix("/")
    if WORKFLOW_CONTAINER_NAME.fullmatch(primary):
        return primary
    return None


def _state_matches(item: WorkflowContainer, state: StateFilter) -> bool:
    if state == "all":
        return True
    label = item.state_label
    if state == "running":
        return label == "running"
    if state == "dead":
        return label == "dead"
    if state == "stopped":
        return label in {"exited", "created", "paused", "restarting", "removing"}


def format_created(created: str) -> str:
    """Trim Docker's verbose CreatedAt when possible."""
    if not created:
        return ""
    if "T" in created:
        try:
            stamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
            return stamp.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    return created[:32]