from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from ai_agent.approval.prompt import ApprovalResult, PendingCommand, auto_approves
from ai_agent.approval.session import ApprovalSession
from ai_agent.commands.render import render_command
from ai_agent.config import ConfirmationMode
from ai_agent.policy.engine import PolicyDecision
from ai_agent.policy.risk import RiskLevel

GRANT_READ_ONLY = "read_only_session"
GRANT_REVERSIBLE = "reversible_session"
_ALLOWED_GRANTS = frozenset({GRANT_READ_ONLY, GRANT_REVERSIBLE})


@dataclass
class OpenApproval:
    approval_id: str
    user_id: str
    conversation_id: str
    risks: list[RiskLevel]
    event: threading.Event = field(default_factory=threading.Event)
    result: ApprovalResult | None = None


class ApprovalBroker:
    """In-process wait for a client to approve commands during a live turn.

    The decision is posted on a second request while the turn stream stays open.
    The broker never reads a user id from that request body.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, OpenApproval] = {}
        self._busy: set[str] = set()

    def try_begin(self, conversation_id: str) -> bool:
        with self._lock:
            if conversation_id in self._busy:
                return False
            self._busy.add(conversation_id)
            return True

    def finish(self, conversation_id: str) -> None:
        with self._lock:
            self._busy.discard(conversation_id)

    def register(self, approval: OpenApproval) -> None:
        with self._lock:
            self._pending[approval.approval_id] = approval

    def drop(self, approval_id: str) -> None:
        with self._lock:
            self._pending.pop(approval_id, None)

    def resolve(
        self,
        *,
        user_id: str,
        conversation_id: str,
        approval_id: str,
        approved: bool,
        grant_scope: str | None,
    ) -> bool:
        with self._lock:
            approval = self._pending.get(approval_id)
            if approval is None:
                return False
            if approval.user_id != user_id or approval.conversation_id != conversation_id:
                return False
            if approval.event.is_set():
                return False
            approval.result = ApprovalResult(
                approved=approved,
                grant_scope=_accepted_grant(approval.risks, grant_scope),
            )
            approval.event.set()
            return True


class RemoteApprovalPrompter:
    """Ask the connected client instead of reading stdin on the server."""

    def __init__(
        self,
        mode: ConfirmationMode,
        session: ApprovalSession,
        broker: ApprovalBroker,
        *,
        user_id: str,
        conversation_id: str,
        emit,
        cancel: threading.Event,
        timeout: float,
    ):
        self.mode = mode
        self.session = session
        self.broker = broker
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.emit = emit
        self.cancel = cancel
        self.timeout = timeout

    def should_auto_run(self, decision: PolicyDecision) -> bool:
        return auto_approves(self.session, self.mode, decision)

    def prompt_single(
        self,
        decision: PolicyDecision,
        *,
        reason: str | None = None,
        target_display: str | None = None,
    ) -> ApprovalResult:
        if not decision.allowed or self.should_auto_run(decision):
            return ApprovalResult(approved=decision.allowed and self.should_auto_run(decision))
        return self._wait(
            [
                _command_summary(
                    decision,
                    reason=reason,
                    target_display=target_display,
                )
            ]
        )

    def prompt_batch(self, pending: list[PendingCommand]) -> ApprovalResult:
        if not pending:
            return ApprovalResult(approved=True)
        if any(not item.decision.allowed for item in pending):
            return ApprovalResult(approved=False)
        if any(item.decision.effective_risk != RiskLevel.READ_ONLY for item in pending):
            for item in pending:
                result = self.prompt_single(
                    item.decision,
                    reason=item.reason,
                    target_display=item.target_display,
                )
                if not result.approved:
                    return ApprovalResult(approved=False)
            return ApprovalResult(approved=True)
        if self.mode == ConfirmationMode.PERMISSIVE or (
            self.mode == ConfirmationMode.BALANCED and self.session.has_read_only_auto()
        ):
            return ApprovalResult(approved=True)
        return self._wait(
            [
                _command_summary(
                    item.decision,
                    reason=item.reason,
                    target_display=item.target_display,
                )
                for item in pending
            ]
        )

    def _wait(self, commands: list[dict]) -> ApprovalResult:
        approval = OpenApproval(
            approval_id=str(uuid.uuid4()),
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            risks=[_risk_from_summary(item) for item in commands],
        )
        self.broker.register(approval)
        self.emit(
            {
                "type": "approval_required",
                "approval_id": approval.approval_id,
                "conversation_id": self.conversation_id,
                "commands": commands,
            }
        )
        deadline = time.monotonic() + self.timeout
        try:
            while not approval.event.wait(timeout=0.25):
                if self.cancel.is_set() or time.monotonic() >= deadline:
                    return ApprovalResult(approved=False)
        finally:
            self.broker.drop(approval.approval_id)
        result = approval.result or ApprovalResult(approved=False)
        if result.approved and result.grant_scope == GRANT_READ_ONLY:
            self.session.enable_read_only_auto()
        elif result.approved and result.grant_scope == GRANT_REVERSIBLE:
            self.session.add_grant(RiskLevel.REVERSIBLE, "global")
        return result


def _command_summary(
    decision: PolicyDecision,
    *,
    reason: str | None,
    target_display: str | None,
) -> dict:
    return {
        "command": render_command(decision.expr),
        "risk": decision.effective_risk.label(),
        "reason": reason or decision.reason,
        "allowed": decision.allowed,
        "target": target_display,
    }


def _risk_from_summary(item: dict) -> RiskLevel:
    try:
        return RiskLevel[item["risk"]]
    except KeyError:
        return RiskLevel.DESTRUCTIVE


def _accepted_grant(risks: list[RiskLevel], grant_scope: str | None) -> str | None:
    if grant_scope not in _ALLOWED_GRANTS:
        return None
    if grant_scope == GRANT_READ_ONLY and any(risk != RiskLevel.READ_ONLY for risk in risks):
        return None
    if grant_scope == GRANT_REVERSIBLE and any(
        risk not in {RiskLevel.READ_ONLY, RiskLevel.REVERSIBLE} for risk in risks
    ):
        return None
    return grant_scope
