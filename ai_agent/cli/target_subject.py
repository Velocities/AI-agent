from __future__ import annotations

from ai_agent.api.auth import InvalidTokenError, build_verifier
from ai_agent.config import Settings
from ai_agent.deployment.operator_session import load_operator_session, session_is_fresh


class TargetSubjectError(ValueError):
    """Could not determine which Supabase user owns the operation."""


def resolve_subject_user_id(
    settings: Settings,
    *,
    user_id_flag: str | None,
) -> str:
    """Require a Supabase user id for execution-target commands.

    Prefer --user-id when supplied; otherwise use ai-agent-chat login session sub.
    """
    if user_id_flag and user_id_flag.strip():
        return user_id_flag.strip()
    session = load_operator_session()
    if session is None or not session_is_fresh(session):
        raise TargetSubjectError(
            "Supabase user id is required. Run ai-agent-chat login on this machine, "
            "or pass --user-id <uuid>."
        )
    verifier = build_verifier(settings)
    if verifier is None:
        raise TargetSubjectError(
            "SUPABASE_URL is not configured; pass --user-id explicitly."
        )
    try:
        user = verifier.verify(session.access_token)
    except InvalidTokenError as exc:
        raise TargetSubjectError(
            "Session expired or invalid. Run ai-agent-chat login again."
        ) from exc
    return user.user_id