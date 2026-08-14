from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ai_agent.config import ConfirmationMode
from ai_agent.policy.risk import RiskLevel


@dataclass
class SessionGrant:
    grant_id: str
    risk_level: RiskLevel
    scope: str
    expires_at: datetime


@dataclass
class ApprovalSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    grants: list[SessionGrant] = field(default_factory=list)
    read_only_batch_auto: bool = False

    def add_grant(
        self,
        risk_level: RiskLevel,
        scope: str,
        *,
        minutes: int = 30,
    ) -> SessionGrant:
        grant = SessionGrant(
            grant_id=str(uuid.uuid4()),
            risk_level=risk_level,
            scope=scope,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=minutes),
        )
        self.grants.append(grant)
        return grant

    def has_grant(self, risk_level: RiskLevel, scope: str) -> bool:
        now = datetime.now(timezone.utc)
        for grant in self.grants:
            if grant.expires_at < now:
                continue
            if grant.risk_level.value >= risk_level.value and grant.scope == scope:
                return True
        return False

    def has_read_only_auto(self) -> bool:
        return self.read_only_batch_auto

    def enable_read_only_auto(self) -> None:
        self.read_only_batch_auto = True


def risk_requires_confirmation(
    risk: RiskLevel,
    mode: ConfirmationMode,
    session: ApprovalSession,
) -> bool:
    if risk == RiskLevel.FORBIDDEN:
        return False
    if risk == RiskLevel.READ_ONLY:
        if session.has_read_only_auto():
            return False
        if mode == ConfirmationMode.PARANOID:
            return True
        return mode != ConfirmationMode.BALANCED
    if mode == ConfirmationMode.PERMISSIVE:
        return risk.value >= RiskLevel.DESTRUCTIVE.value
    return True
