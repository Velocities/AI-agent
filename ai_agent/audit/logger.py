from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai_agent.commands.render import render_command
from ai_agent.policy.engine import PolicyDecision
from ai_agent.policy.risk import RiskLevel


@dataclass
class AuditRecord:
    timestamp: str
    session_id: str
    user: str
    tool_name: str
    arguments: dict
    rendered_command: str
    risk_level: str
    confirmation_required: bool
    confirmation_granted: bool | None
    allowed: bool
    success: bool | None
    exit_status: int | None
    duration_ms: int | None
    error: str | None
    stdout_preview: str | None = None
    stderr_preview: str | None = None


class AuditLogger:
    def __init__(self, log_path: Path | None = None, user: str = "ai"):
        self.log_path = log_path
        self.user = user
        self.logger = logging.getLogger("ai_agent.audit")

    def log_event(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict,
        decision: PolicyDecision,
        confirmation_required: bool,
        confirmation_granted: bool | None,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        record = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            user=self.user,
            tool_name=tool_name,
            arguments=arguments,
            rendered_command=render_command(decision.expr),
            risk_level=decision.effective_risk.label(),
            confirmation_required=confirmation_required,
            confirmation_granted=confirmation_granted,
            allowed=decision.allowed,
            success=result.get("success") if result else None,
            exit_status=result.get("exit_status") if result else None,
            duration_ms=result.get("duration_ms") if result else None,
            error=error,
            stdout_preview=(result or {}).get("stdout", "")[:500] or None,
            stderr_preview=(result or {}).get("stderr", "")[:500] or None,
        )
        payload = asdict(record)
        redacted = self._redact(payload)
        line = json.dumps(redacted, ensure_ascii=True)
        self.logger.info(line)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    @staticmethod
    def _redact(payload: dict) -> dict:
        sensitive_keys = {"password", "token", "secret", "api_key", "authorization"}
        def scrub(value, key=""):
            if isinstance(value, dict):
                return {
                    key: scrub(item, key)
                    for key, item in value.items()
                    if key.lower() not in sensitive_keys
                }
            if isinstance(value, list):
                return [scrub(item) for item in value]
            return value
        return scrub(payload)
