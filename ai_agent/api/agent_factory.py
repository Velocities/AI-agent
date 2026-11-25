from __future__ import annotations

from getpass import getuser

from ai_agent.agent.factory import build_agent
from ai_agent.config import Settings
from ai_agent.conversations.user_settings import UserSettingsStore
from ai_agent.deployment.access import AccessStatus
from ai_agent.deployment.access_store import DeploymentAccessStore
from ai_agent.execution_targets.repository import UserExecutionTargetRepository
from ai_agent.workflows.manifests import WorkflowError
from ai_agent.workflows.runtime import ensure_workflow_container, open_attached_workflow


def build_api_agent_factory(
    access_store: DeploymentAccessStore | None,
    target_repo: UserExecutionTargetRepository | None,
    user_settings: UserSettingsStore | None = None,
):
    """Agent factory for API turns: local commands run as the approved Linux user."""

    def factory(
        *,
        settings: Settings,
        prompter,
        session,
        audit_user: str,
        workflow_attachment=None,
    ):
        linux_username = _linux_username_for(audit_user, access_store)
        scratch = settings.agent_scratch_dir
        if linux_username:
            scratch = scratch / linux_username
        settings = settings.model_copy(update={"agent_scratch_dir": scratch})
        personalization = None
        if user_settings is not None:
            personalization = user_settings.get_preferences(audit_user)
        workflow_session = None
        if workflow_attachment is not None:
            owner = linux_username or _process_user()
            workflow_session = open_attached_workflow(workflow_attachment, owner)
            ensure_workflow_container(workflow_session)
            linux_username = owner
        return build_agent(
            prompter=prompter,
            session=session,
            audit_user=audit_user,
            settings=settings,
            run_as_linux_user=linux_username,
            user_id=audit_user,
            target_repo=target_repo,
            access_store=access_store,
            personalization=personalization,
            workflow_session=workflow_session,
        )

    return factory


def _process_user() -> str:
    name = getuser()
    if not name or name == "root":
        raise WorkflowError("A Linux username is required before a workflow can run.")
    return name


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
