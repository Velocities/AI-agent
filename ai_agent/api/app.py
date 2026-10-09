from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from ai_agent.api.approvals import ApprovalBroker
from ai_agent.api.auth import AuthenticatedUser, TokenVerifier, build_verifier
from ai_agent.api.client_config import CLIENT_CONFIG_PATH, ClientConfigBody, client_config_for
from ai_agent.api.conversations import router as conversation_router
from ai_agent.api.monitoring import router as monitoring_router
from ai_agent.api.deps import get_current_user, require_deployment_access
from ai_agent.config import Settings
from ai_agent.conversations.store import ConversationStore
from ai_agent.deployment.access_store import DeploymentAccessStore
from ai_agent.deployment.monitoring_admin_store import MonitoringAdminStore

__all__ = ["create_app", "get_current_user"]


def create_app(
    settings: Settings,
    verifier: TokenVerifier | None = None,
    *,
    configure_auth: bool = True,
    store: ConversationStore | None = None,
    access_store: DeploymentAccessStore | None = None,
    monitoring_admin_store: MonitoringAdminStore | None = None,
    broker: ApprovalBroker | None = None,
    enforce_access: bool = True,
) -> FastAPI:
    """Build the public API.

    Pass `verifier` in tests. `configure_auth=False` leaves protected routes
    unavailable even when SUPABASE_URL is set. `store` is the conversation
    database; leave it unset in tests that only hit /health.
    """
    if verifier is not None:
        resolved: TokenVerifier | None = verifier
    elif configure_auth:
        resolved = build_verifier(settings)
    else:
        resolved = None

    app = FastAPI(title="AI Agent", version="0.1.0")
    app.state.verifier = resolved
    app.state.settings = settings
    app.state.store = store
    app.state.access_store = access_store if enforce_access else None
    app.state.monitoring_admin_store = monitoring_admin_store
    app.state.broker = broker or ApprovalBroker()
    app.state.approval_sessions = {}
    app.state.agent_factory = None

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(CLIENT_CONFIG_PATH, response_model=ClientConfigBody)
    def client_config() -> ClientConfigBody:
        body = client_config_for(settings)
        if body is None:
            raise HTTPException(
                status_code=503,
                detail="Supabase is not configured on this server.",
            )
        return body

    @app.get("/api/me")
    def me(user: AuthenticatedUser = Depends(require_deployment_access)) -> dict[str, str]:
        payload = {"user_id": user.user_id}
        if user.email:
            payload["email"] = user.email
        if user.display_name:
            payload["display_name"] = user.display_name
        return payload

    app.include_router(conversation_router)
    app.include_router(monitoring_router)
    return app
