"""Copy workflow state onto the host only after an explicit user choice.

Nothing in here consults the model for the file list or for approval.
auto-approval and session grants do not apply. Files are created by the
same executor used for local commands, which runs as the approved Linux
user. A root executor is refused.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from ai_agent.commands.ast import WriteFileCommand
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.commands.run_as import RunAsCommandExecutor

CHOICE_YES = "yes"
CHOICE_NO = "no"
CHOICE_SELECT = "select"


class PromotionError(ValueError):
    """The copy cannot proceed."""


@dataclass(frozen=True)
class StateItem:
    """One real path from the container, measured by host code."""

    id: str
    path: str
    kind: str
    size: int
    sha256: str
    detail: str = ""


@dataclass(frozen=True)
class PromotionPreview:
    items: tuple[StateItem, ...]


@dataclass(frozen=True)
class PromotionDecision:
    choice: str
    selected_ids: tuple[str, ...] = ()
    # False unless a person produced this decision. The model cannot set it.
    explicit: bool = False


def auto_approves_promotion() -> bool:
    """Promotion is never covered by confirmation mode or a session grant."""
    return False


def user_promotion_decision(
    choice: str,
    selected_ids: list[str] | None = None,
) -> PromotionDecision:
    """Record a choice that came from the user, not from the model."""
    return PromotionDecision(
        choice=choice,
        selected_ids=tuple(selected_ids or ()),
        explicit=True,
    )


def preview_from_files(files: list[tuple[str, bytes, str]]) -> PromotionPreview:
    """Build a preview from container bytes the host itself read.

    Each entry is (container path, contents, kind). kind is ``file`` or
    ``database``. The description text is the size and checksum, not a
    summary supplied by the model.
    """
    items: list[StateItem] = []
    for path, contents, kind in files:
        if kind not in {"file", "database"}:
            raise PromotionError(f"Unknown state kind {kind!r} for {path}")
        if not path.startswith("/work/") and path != "/work":
            raise PromotionError(f"Inspection path {path} is outside /work")
        digest = hashlib.sha256(contents).hexdigest()
        items.append(
            StateItem(
                id=hashlib.sha256(path.encode()).hexdigest()[:12],
                path=path,
                kind=kind,
                size=len(contents),
                sha256=digest,
                detail=f"{kind} {len(contents)} bytes sha256={digest}",
            )
        )
    return PromotionPreview(items=tuple(items))


def selected_items(
    decision: PromotionDecision,
    preview: PromotionPreview,
) -> tuple[StateItem, ...]:
    if not decision.explicit:
        raise PromotionError("Promotion requires an explicit user choice.")
    if decision.choice == CHOICE_NO:
        return ()
    if decision.choice == CHOICE_YES:
        if decision.selected_ids:
            raise PromotionError("Yes copies the whole preview. Omit a selection.")
        return preview.items
    if decision.choice == CHOICE_SELECT:
        known = {item.id: item for item in preview.items}
        chosen: list[StateItem] = []
        for item_id in decision.selected_ids:
            item = known.get(item_id)
            if item is None:
                raise PromotionError(f"Unknown state item {item_id!r}.")
            chosen.append(item)
        return tuple(chosen)
    raise PromotionError("Choice must be yes, no, or select.")


def assert_promotion_executor(executor: CommandExecutor, linux_username: str) -> Path:
    """Return the home directory files may be written under.

    The writer has to be that Linux user. Root on the host is refused even
    when the container process was root.
    """
    if isinstance(executor, RunAsCommandExecutor):
        if executor.linux_username != linux_username:
            raise PromotionError(
                f"Promotion executor is {executor.linux_username}, expected {linux_username}."
            )
        if executor.uid == 0:
            raise PromotionError("Refusing to copy workflow state as root.")
        return Path(executor.home)
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() == 0:
        raise PromotionError("Refusing to copy workflow state as root.")
    current = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if current != linux_username:
        raise PromotionError(
            f"Promotion executor is {current or 'unknown'}, expected {linux_username}."
        )
    return Path.home()


def destination_path(home: Path, relative: str) -> Path:
    """Resolve a user-confirmed relative path and keep it under home."""
    if not relative or relative.startswith("/") or "\0" in relative:
        raise PromotionError(f"Promotion path {relative!r} must stay under the user's home.")
    root = home.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise PromotionError(f"Promotion path {relative!r} escapes the user's home.")
    return candidate


def apply_promotion(
    *,
    decision: PromotionDecision,
    preview: PromotionPreview,
    files: dict[str, str],
    relative_paths: dict[str, str],
    executor: CommandExecutor,
    linux_username: str,
) -> list[CommandResult]:
    """Write the selected preview items as linux_username.

    ``files`` maps container paths to contents the host read. ``relative_paths``
    maps those container paths to a path under the user's home. Both maps are
    produced by the host, not by the model.
    """
    home = assert_promotion_executor(executor, linux_username)
    results: list[CommandResult] = []
    for item in selected_items(decision, preview):
        if item.path not in files or item.path not in relative_paths:
            raise PromotionError(f"No host bytes for preview item {item.path}.")
        target = destination_path(home, relative_paths[item.path])
        result = executor.run(
            WriteFileCommand(path=str(target), content=files[item.path])
        )
        results.append(result)
        if not result.success:
            break
    return results
