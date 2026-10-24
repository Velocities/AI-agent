"""Per-command batch decisions, including ordered cascades.

An ordered batch is one sequence: the first command the user rejects also
rejects every command after it, because a later step may depend on an earlier
one. An unordered batch lets the user accept any subset. A turn can mix both
when several tool calls are approved together; each ordered run_commands call
is its own sequence and a rejection stays inside that sequence.
"""

from __future__ import annotations

ORDERED = "ordered"
UNORDERED = "unordered"
MIXED = "mixed"

_DECISIONS = frozenset({"accept", "reject"})


class InvalidApprovalDecision(ValueError):
    """The client named a command this approval does not contain."""


def batch_ordering(arguments: dict) -> tuple[str, str | None]:
    """Return (ordering, error). A missing value stays unordered.

    Older tool calls omit the field. An explicit value that is neither
    ordered nor unordered is an error so the model can correct it.
    """
    if "ordering" not in arguments:
        return UNORDERED, None
    value = arguments.get("ordering")
    if value in {ORDERED, UNORDERED}:
        return value, None
    return UNORDERED, 'ordering must be "ordered" or "unordered".'


def order_groups_for(ordering: str, count: int) -> list[int | None]:
    """One sequence id for an ordered batch; None marks an independent command."""
    if ordering == ORDERED and count:
        return [0] * count
    return [None] * count


def normalize_groups(groups: list[int | None] | None, count: int) -> list[int | None]:
    if groups is None or len(groups) != count:
        return [None] * count
    return list(groups)


def describe_ordering(groups: list[int | None]) -> str:
    present = [group for group in groups if group is not None]
    if not present:
        return UNORDERED
    if len(present) == len(groups) and len(set(present)) == 1:
        return ORDERED
    return MIXED


def apply_cascade(chosen: list[bool], groups: list[int | None]) -> list[bool]:
    """Drop every later accept in a sequence once that sequence has a rejection."""
    blocked: set[int] = set()
    final: list[bool] = []
    for accept, group in zip(chosen, groups, strict=True):
        if group is not None and group in blocked:
            final.append(False)
            continue
        if not accept:
            final.append(False)
            if group is not None:
                blocked.add(group)
            continue
        final.append(True)
    return final


def resolve_selection(
    chosen: list[bool],
    groups: list[int | None],
) -> tuple[bool, tuple[bool, ...] | None, tuple[bool, ...] | None]:
    """Return (approved, accepted, cascade_rejected).

    accepted is None when every command is approved or every command is
    rejected, so those outcomes stay identical to approve-all and reject-all.
    cascade_rejected is true where the user had accepted a command and the
    ordered rule rejected it.
    """
    aligned = normalize_groups(groups, len(chosen))
    final = apply_cascade(chosen, aligned)
    if not final or all(final) or not any(final):
        return (bool(final) and all(final), None, None)
    cascade = tuple(want and not got for want, got in zip(chosen, final, strict=True))
    return (False, tuple(final), cascade)


def resolve_choices(
    decisions: list[tuple[int, str]],
    count: int,
    groups: list[int | None],
) -> tuple[bool, tuple[bool, ...] | None, tuple[bool, ...] | None]:
    """Map 1-based accept/reject ids onto the batch, then apply ordering."""
    if count < 1:
        raise InvalidApprovalDecision("This approval has no commands.")
    chosen = [False] * count
    seen: set[int] = set()
    for command_id, decision in decisions:
        if isinstance(command_id, bool) or not isinstance(command_id, int):
            raise InvalidApprovalDecision(f"Command id {command_id} is not in this batch.")
        if command_id < 1 or command_id > count:
            raise InvalidApprovalDecision(f"Command id {command_id} is not in this batch.")
        if command_id in seen:
            raise InvalidApprovalDecision(f"Command id {command_id} was sent more than once.")
        if decision not in _DECISIONS:
            raise InvalidApprovalDecision('Each decision must be "accept" or "reject".')
        seen.add(command_id)
        chosen[command_id - 1] = decision == "accept"
    if len(seen) != count:
        missing = ", ".join(str(index) for index in range(1, count + 1) if index not in seen)
        raise InvalidApprovalDecision(f"Every command needs a decision. Missing: {missing}.")
    return resolve_selection(chosen, groups)


def approval_flags(
    approved: bool,
    accepted: tuple[bool, ...] | None,
    count: int,
) -> list[bool]:
    if accepted is not None and len(accepted) == count:
        return [bool(item) for item in accepted]
    return [approved] * count


def partial_batch_note(rows: list[tuple[str, bool, bool]]) -> str | None:
    """Tell the model which commands in a partial batch were approved.

    Each row is (rendered command, accepted, rejected by the ordered rule).
    All-approved and all-rejected batches return None so their tool results
    stay the same as approve-all and reject-all.
    """
    if not rows or all(ok for _, ok, _ in rows) or not any(ok for _, ok, _ in rows):
        return None
    approved = [
        f"{index}. {command}"
        for index, (command, ok, _) in enumerate(rows, start=1)
        if ok
    ]
    rejected = [
        f"{index}. {command}"
        for index, (command, ok, cascaded) in enumerate(rows, start=1)
        if not ok and not cascaded
    ]
    cascaded_rows = [
        f"{index}. {command}"
        for index, (command, ok, cascaded) in enumerate(rows, start=1)
        if not ok and cascaded
    ]
    parts = [
        "The user only approved these commands you requested in the batch: "
        + "; ".join(approved)
        + "."
    ]
    if rejected:
        parts.append("The user rejected: " + "; ".join(rejected) + ".")
    if cascaded_rows:
        parts.append(
            "These were rejected because an earlier command in this ordered batch "
            "was rejected: " + "; ".join(cascaded_rows) + "."
        )
    return " ".join(parts)


def apply_batch_approval(
    payloads: list[dict],
    *,
    accepted: tuple[bool, ...] | None,
    cascade_rejected: tuple[bool, ...] | None,
) -> None:
    """Attach the partial-approval note without changing result order.

    Each payload keeps its own stdout or denial. The note is repeated on every
    command so the model sees which commands ran and which did not.
    """
    if accepted is None or len(accepted) != len(payloads):
        return
    cascade = cascade_rejected or ()
    if len(cascade) != len(payloads):
        cascade = tuple(False for _ in payloads)
    rows: list[tuple[str, bool, bool]] = []
    for index, payload in enumerate(payloads):
        command = str(payload.get("rendered_command") or "command")
        rows.append((command, bool(accepted[index]), bool(cascade[index])))
    note = partial_batch_note(rows)
    if note is None:
        return
    ordered_denial = (
        "Rejected because an earlier command in this ordered batch was rejected."
    )
    for index, payload in enumerate(payloads):
        if cascade[index]:
            payload["success"] = False
            payload["user_denied"] = True
            payload["rejected_by_order"] = True
            payload["error"] = ordered_denial
        prefix = {
            "batch_approval": note,
            "command_id": index + 1,
            "user_decision": "accept" if accepted[index] else "reject",
        }
        merged = {**prefix, **payload}
        payload.clear()
        payload.update(merged)
