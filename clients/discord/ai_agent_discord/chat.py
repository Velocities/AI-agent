"""Chat actions shared by slash commands and channel messages.

These functions talk to a deployment through AgentApiClient. They return text.
Discord embeds and the wait line are applied by the bot.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx

from ai_agent_client.api import AgentApiClient, AgentApiError
from ai_agent_client.types import ImageInput
from ai_agent_cli.api_url import public_api_base_url_hint
from ai_agent_cli.client_state import normalize_server_url, session_is_fresh
from ai_agent_cli.contracts import WorkflowStatus, workflow_status_text
from ai_agent_cli.images import ImageRejected, maybe_strip_for_transit, validate_image_bytes
from ai_agent_cli.login import refresh_session
from ai_agent_cli.server_config import fetch_client_config
from ai_agent_cli.terminal_chat import model_info_lines
from ai_agent_discord.present import explain_api_error, explain_unreachable
from ai_agent_discord.store import Deployment, StoreError, UserStore


class ChatProblem(Exception):
    def __init__(self, message: str, *, deployment: str | None = None):
        super().__init__(message)
        self.deployment = deployment


@dataclass
class Reply:
    text: str
    deployment: str | None = None
    ephemeral: bool = False
    conversations: list[dict] | None = None


@dataclass
class TurnText:
    """Fold a turn's streamed events into the text Discord will show."""

    parts: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    def feed(self, event: dict) -> str | None:
        kind = event.get("type")
        if kind == "token":
            self.tokens.append(str(event.get("text") or ""))
            return None
        if kind == "notice":
            self._flush_tokens()
            self.parts.append(f"· {event.get('text', '')}")
            return None
        if kind == "status":
            self._flush_tokens()
            text = str(event.get("text") or "").strip()
            if text:
                self.parts.append(text)
            return None
        if kind == "done":
            self._flush_tokens()
            error = event.get("error")
            if error:
                self.parts.append(str(error))
            return None
        if kind == "error":
            return str(event.get("message") or "Turn failed.")
        return None

    def finish(self) -> str:
        self._flush_tokens()
        return "\n".join(part for part in self.parts if part).strip()

    def _flush_tokens(self) -> None:
        if not self.tokens:
            return
        self.parts.append("".join(self.tokens))
        self.tokens.clear()


def message_for_bot(
    *,
    is_dm: bool,
    mentions_bot: bool,
    replies_to_bot: bool,
    content: str,
    bot_id: int,
    has_images: bool,
) -> str | None:
    """Turn text when this message is for the bot, or None to stay quiet.

    An empty string means the message has images and no remaining text.
    """
    if not is_dm and not mentions_bot and not replies_to_bot:
        return None
    cleaned = " ".join(re.sub(rf"<@!?{bot_id}>", " ", content).split())
    if not cleaned and not has_images:
        return None
    return cleaned


def images_from_parts(blobs: list[tuple[str, bytes]]) -> list[ImageInput]:
    images: list[ImageInput] = []
    for name, data in blobs:
        try:
            image = validate_image_bytes(data)
        except ImageRejected as exc:
            raise ChatProblem(f"{name}: {exc}") from exc
        images.append(maybe_strip_for_transit(image))
    return images


def require_deployment(store: UserStore, user_id: int) -> Deployment:
    deployment = store.active_deployment(user_id)
    if deployment is None:
        raise ChatProblem(
            "No deployment is selected. Add one with /server use and the server URL."
        )
    return deployment


def access_token(store: UserStore, user_id: int, deployment: Deployment) -> str:
    session = store.session_for(user_id, deployment.server_url)
    if session is None:
        raise ChatProblem(
            f"Not signed in to {deployment.server_url}. Run /login.",
            deployment=deployment.server_url,
        )
    if session_is_fresh(session):
        return session.access_token
    try:
        refreshed = refresh_session(
            supabase_url=deployment.supabase_url,
            anon_key=deployment.supabase_publishable_key,
            refresh_token=session.refresh_token,
        )
    except httpx.HTTPError as exc:
        raise ChatProblem(
            "Could not refresh sign-in. Run /login.",
            deployment=deployment.server_url,
        ) from exc
    store.save_session(user_id, deployment.server_url, refreshed)
    return refreshed.access_token


@contextmanager
def client_for(store: UserStore, user_id: int, deployment: Deployment):
    client = AgentApiClient(deployment.server_url, access_token(store, user_id, deployment))
    try:
        yield client
    finally:
        client.close()


def guard(deployment: str, fn):
    try:
        return fn()
    except ChatProblem as exc:
        if exc.deployment is None:
            exc.deployment = deployment
        raise
    except AgentApiError as exc:
        raise ChatProblem(explain_api_error(exc), deployment=deployment) from exc
    except httpx.HTTPError as exc:
        raise ChatProblem(explain_unreachable(deployment, exc), deployment=deployment) from exc


def use_deployment(
    store: UserStore,
    user_id: int,
    raw: str,
    *,
    fetch=fetch_client_config,
) -> Reply:
    try:
        origin = normalize_server_url(raw)
    except ValueError as exc:
        raise ChatProblem(str(exc)) from exc
    try:
        config = fetch(origin)
    except ValueError as exc:
        raise ChatProblem(str(exc), deployment=origin) from exc
    except httpx.HTTPError as exc:
        raise ChatProblem(explain_unreachable(origin, exc), deployment=origin) from exc
    previous = store.find(user_id, config.server_url)
    supabase_changed = previous is not None and (
        previous.supabase_url != config.supabase_url
        or previous.supabase_publishable_key != config.supabase_publishable_key
    )
    conversation_id = None if previous is None or supabase_changed else previous.conversation_id
    if supabase_changed:
        store.clear_session(user_id, config.server_url)
    deployment = Deployment(
        server_url=config.server_url,
        supabase_url=config.supabase_url,
        supabase_publishable_key=config.supabase_publishable_key,
        conversation_id=conversation_id,
    )
    store.save_deployment(user_id, deployment)
    lines = [f"Using {deployment.server_url}."]
    if store.session_for(user_id, deployment.server_url) is None:
        lines.append("Not signed in on this deployment. Run /login.")
    hint = public_api_base_url_hint(deployment.server_url)
    if hint:
        lines.append(hint)
    return Reply(text="\n".join(lines), deployment=deployment.server_url)


def forget_deployment(store: UserStore, user_id: int, raw: str) -> Reply:
    try:
        origin = normalize_server_url(raw)
    except ValueError as exc:
        raise ChatProblem(str(exc)) from exc
    current = store.active_deployment(user_id)
    try:
        remaining = store.remove_deployment(user_id, origin)
    except StoreError as exc:
        raise ChatProblem(str(exc), deployment=None if current is None else current.server_url) from exc
    lines = [f"Removed {origin}."]
    if remaining is None:
        lines.append("No deployments saved.")
        return Reply(text="\n".join(lines))
    lines.append(f"Using {remaining.server_url}.")
    if store.session_for(user_id, remaining.server_url) is None:
        lines.append("Not signed in on this deployment. Run /login.")
    return Reply(text="\n".join(lines), deployment=remaining.server_url)


def list_deployments(store: UserStore, user_id: int) -> Reply:
    servers = store.list_deployments(user_id)
    active = store.active_deployment(user_id)
    if not servers:
        return Reply(
            text="No deployments saved. Add one with /server use and the server URL."
        )
    lines = []
    for server in servers:
        mark = "*" if active is not None and server.server_url == active.server_url else " "
        lines.append(f"{mark} {server.server_url}")
    lines.append("/server use adds or switches. /server remove forgets one.")
    deployment = active.server_url if active is not None else None
    return Reply(text="\n".join(lines), deployment=deployment)


def login_message(url: str, deployment: Deployment, redirect_url: str) -> Reply:
    text = (
        f"Open this link to sign in to {deployment.server_url}:\n{url}\n\n"
        f"Add {redirect_url} to that deployment's Supabase redirect allow list "
        "if this is the first Discord login there."
    )
    return Reply(text=text, deployment=deployment.server_url, ephemeral=True)


def logout(store: UserStore, user_id: int) -> Reply:
    deployment = require_deployment(store, user_id)
    store.clear_session(user_id, deployment.server_url)
    return Reply(
        text=f"Signed out of {deployment.server_url}.",
        deployment=deployment.server_url,
    )


def start_new(store: UserStore, user_id: int) -> Reply:
    deployment = require_deployment(store, user_id)

    def run() -> Reply:
        with client_for(store, user_id, deployment) as client:
            created = client.create_conversation()
        conversation_id = str(created["id"])
        store.set_conversation(user_id, deployment.server_url, conversation_id)
        return Reply(text="Started a new chat.", deployment=deployment.server_url)

    return guard(deployment.server_url, run)


def list_chats(store: UserStore, user_id: int) -> Reply:
    deployment = require_deployment(store, user_id)

    def run() -> Reply:
        with client_for(store, user_id, deployment) as client:
            rows = client.list_conversations()
        if not rows:
            return Reply(text="No chats yet.", deployment=deployment.server_url)
        current = deployment.conversation_id
        shown = rows[:25]
        lines = []
        for row in shown:
            mark = "*" if row.get("id") == current else " "
            title = row.get("title") or "Untitled"
            workflow = row.get("workflow") or {}
            workflow_name = workflow.get("name") if isinstance(workflow, dict) else ""
            label = f"{title} ({workflow_name})" if workflow_name else title
            lines.append(f"{mark} {label}  {row.get('id')}")
        if len(rows) > len(shown):
            lines.append(f"Showing {len(shown)} of {len(rows)} chats, newest first.")
        lines.append("Choose a chat in the menu to continue it.")
        return Reply(
            text="\n".join(lines),
            deployment=deployment.server_url,
            conversations=shown,
        )

    return guard(deployment.server_url, run)


def continue_chat(store: UserStore, user_id: int, conversation_id: str) -> Reply:
    deployment = require_deployment(store, user_id)

    def run() -> Reply:
        with client_for(store, user_id, deployment) as client:
            document = client.get_conversation(conversation_id)
        store.set_conversation(user_id, deployment.server_url, conversation_id)
        title = document.get("title") or "Untitled"
        return Reply(text=f"Continuing {title}.", deployment=deployment.server_url)

    return guard(deployment.server_url, run)


def model_text(store: UserStore, user_id: int) -> Reply:
    deployment = require_deployment(store, user_id)

    def run() -> Reply:
        with client_for(store, user_id, deployment) as client:
            try:
                document = client.get_model()
            except AgentApiError as exc:
                if exc.status != 503:
                    raise
                document = None
        if not isinstance(document, dict):
            document = None
        return Reply(
            text="\n".join(model_info_lines(document)),
            deployment=deployment.server_url,
        )

    return guard(deployment.server_url, run)


def workflow_command(store: UserStore, user_id: int, argument: str) -> Reply:
    deployment = require_deployment(store, user_id)

    def run() -> Reply:
        with client_for(store, user_id, deployment) as client:
            catalog = client.list_workflows()
            if not argument.strip():
                return Reply(
                    text=format_workflows(catalog),
                    deployment=deployment.server_url,
                )
            name, given = parse_workflow_argument(argument)
            match = next((item for item in catalog if item.get("name") == name), None)
            if match is None:
                return Reply(
                    text=f"No workflow named {name}.\n{format_workflows(catalog)}",
                    deployment=deployment.server_url,
                )
            missing = _missing_parameters(match, given)
            if missing:
                joined = ", ".join(missing)
                return Reply(
                    text=(
                        f"Missing required parameters: {joined}.\n"
                        f"Start it with /workflow {name} key=value"
                    ),
                    deployment=deployment.server_url,
                )
            created = client.create_conversation(
                title=name,
                workflow=name,
                parameters=given,
            )
        conversation_id = str(created.get("id") or "")
        if conversation_id:
            store.set_conversation(user_id, deployment.server_url, conversation_id)
        return Reply(
            text=workflow_started_text(created),
            deployment=deployment.server_url,
        )

    return guard(deployment.server_url, run)


def bind_conversation(
    client: AgentApiClient,
    store: UserStore,
    user_id: int,
    deployment: Deployment,
) -> tuple[str, str]:
    """Return the conversation id to send to, and a notice when resuming an old chat."""
    saved = deployment.conversation_id
    if saved:
        try:
            client.get_conversation(saved)
        except AgentApiError as exc:
            if exc.status != 404:
                raise
            store.set_conversation(user_id, deployment.server_url, None)
        else:
            return saved, ""
    rows = client.list_conversations()
    if rows:
        conversation_id = str(rows[0]["id"])
        store.set_conversation(user_id, deployment.server_url, conversation_id)
        title = rows[0].get("title") or "Untitled"
        return conversation_id, f"Resuming {title}."
    created = client.create_conversation()
    conversation_id = str(created["id"])
    store.set_conversation(user_id, deployment.server_url, conversation_id)
    return conversation_id, ""


def ensure_images_allowed(client: AgentApiClient) -> None:
    try:
        document = client.get_model()
    except AgentApiError as exc:
        if exc.status == 503:
            return
        raise
    if isinstance(document, dict) and document.get("vision") is False:
        raise ChatProblem("This deployment's model does not accept images.")


def workflow_gate(document: dict) -> str | None:
    """Text when a message must wait, or None when sending is allowed."""
    workflow = document.get("workflow")
    if not isinstance(workflow, dict):
        return None
    status = str(workflow.get("status") or "")
    if not status or status == WorkflowStatus.IS_READY:
        return None
    try:
        line = workflow_status_text(WorkflowStatus(status))
    except ValueError:
        line = "The workflow is not ready yet. You can type. Sending waits until it is ready."
    error = str(workflow.get("error") or "").strip()
    if status == WorkflowStatus.IS_FAILED and error:
        line = f"{line} {error}"
    return line


def parse_workflow_argument(argument: str) -> tuple[str, dict[str, str]]:
    parts = argument.split()
    if not parts:
        return "", {}
    name = parts[0]
    given: dict[str, str] = {}
    for part in parts[1:]:
        key, separator, value = part.partition("=")
        if not separator or not key:
            continue
        given[key] = value
    return name, given


def format_workflows(catalog: list[dict]) -> str:
    if not catalog:
        return "This deployment has no workflows."
    lines = ["Workflows"]
    for item in catalog:
        name = item.get("name") or ""
        description = item.get("description") or ""
        lines.append(f"  {name}  {description}".rstrip())
        for parameter in item.get("parameters") or []:
            if not isinstance(parameter, dict):
                continue
            mark = "required" if parameter.get("required") else "optional"
            lines.append(
                f"    {parameter.get('name')} ({mark})  {parameter.get('description') or ''}".rstrip()
            )
    lines.append("Start one with /workflow name key=value")
    return "\n".join(lines)


def workflow_started_text(created: dict) -> str:
    workflow = created.get("workflow") if isinstance(created.get("workflow"), dict) else {}
    name = workflow.get("name") if isinstance(workflow, dict) else ""
    lines = [f"Started workflow {name or created.get('title') or 'chat'}."]
    if isinstance(workflow, dict) and str(workflow.get("status") or "") == WorkflowStatus.IS_READY:
        lines.append(workflow_status_text(WorkflowStatus.IS_READY))
    else:
        gate = workflow_gate(created)
        if gate:
            lines.append(gate)
    return "\n".join(lines)


def _missing_parameters(workflow: dict, given: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for parameter in workflow.get("parameters") or []:
        if not isinstance(parameter, dict) or not parameter.get("required"):
            continue
        name = str(parameter.get("name") or "")
        if name and name not in given:
            missing.append(name)
    return missing
