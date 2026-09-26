from __future__ import annotations

from ai_agent.cli.app import build_agent
from ai_agent.config import Settings
from ai_agent.deployment.access import AccessStatus
from ai_agent.deployment.access_store import DeploymentAccessStore


def build_api_agent_factory(
    access_store: DeploymentAccessStore | None,
):
    """Agent factory for API turns: local commands run as the approved Linux user."""

    def factory(
        *,
        settings: Settings,
        prompter,
        session,
        audit_user: str,
    ):
        linux_username = _linux_username_for(audit_user, access_store)
        scratch = settings.agent_scratch_dir
        if linux_username:
            scratch = scratch / linux_username
        settings = settings.model_copy(update={"agent_scratch_dir": scratch})
        return build_agent(
            prompter=prompter,
            session=session,
            audit_user=audit_user,
            settings=settings,
            run_as_linux_user=linux_username,
        )

    return factory


def _linux_username_for(
    user_id: str,
    access_store: DeploymentAccessStore | None,
) -> str | None:
    if access_store is None:
        return None
    record = access_store.get(user_id)
    if record is None or record.status != AccessStatus.APPROVED:
        return None
    name = record.linux_username.strip()
    return name or None
