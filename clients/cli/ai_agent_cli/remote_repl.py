from __future__ import annotations

import httpx
from rich.console import Console

from ai_agent.cli.image_stage import ImageStage, StageCommand
from ai_agent.deployment.access import ACCESS_DENIED_CODE, ACCESS_PENDING_CODE
from ai_agent.images import ImageRejected
from ai_agent.llm.client.types import ImageInput
from ai_agent_cli.api_client import AgentApiClient, AgentApiError
from ai_agent_cli.api_url import public_api_base_url_hint
from ai_agent_cli.credentials import (
    load_conversation_id,
    load_session,
    save_conversation_id,
    save_session,
    session_is_fresh,
)
from ai_agent_cli.login import refresh_session
from ai_agent_cli.server_config import ServerConfig, ensure_server_config, set_server_url


def run_remote_repl() -> int:
    console = Console()
    config = ensure_server_config(console)
    if config is None:
        return 1
    token = _access_token(config, console)
    if token is None:
        return 1

    client = AgentApiClient(config.server_url, token)
    try:
        conversation_id = _current_conversation(client, console)
        vision = _model_vision(client, console)
    except AgentApiError as exc:
        _print_access_error(console, exc)
        client.close()
        return 1
    except httpx.HTTPError as exc:
        console.print(f"[red]Cannot reach {config.server_url}:[/red] {exc}")
        console.print(
            "Start [bold]ai-agent serve[/bold] on the model machine and try again."
        )
        client.close()
        return 1

    console.print("[bold]AI Server Assistant[/bold]")
    console.print(f"API: {config.server_url}")
    if hint := public_api_base_url_hint(config.server_url):
        console.print(f"[yellow]{hint}[/yellow]")
    console.print("Type /new, /list, /server, /attach, or exit.\n")
    stage = ImageStage(vision=vision)

    try:
        while True:
            try:
                user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nGoodbye.")
                return 0
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                stage.clear()
                console.print("Goodbye.")
                return 0
            if user_input == "/list":
                if not _print_conversations(client, console):
                    return 1
                continue
            if user_input == "/server" or user_input.startswith("/server "):
                updated = _apply_server_command(
                    console,
                    config,
                    user_input[len("/server") :].strip(),
                )
                if updated is None:
                    return 0
                config = updated
                continue
            if user_input == "/new":
                stage.clear()
                created = _create_conversation(client, console)
                if created is None:
                    return 1
                conversation_id = created["id"]
                save_conversation_id(conversation_id)
                console.print("[dim]Started a new chat.[/dim]")
                continue
            try:
                command = stage.handle(user_input)
            except ImageRejected as exc:
                console.print(f"[red]{exc}[/red]")
                continue
            if command.handled:
                _print_stage(console, command)
                continue
            images = stage.take()
            if images and not vision:
                console.print("[red]This server's model does not accept images.[/red]")
                continue
            if not _play_turn(client, console, conversation_id, user_input, images):
                return 1
            console.print()
    finally:
        client.close()


def _model_vision(client: AgentApiClient, console: Console) -> bool:
    try:
        document = client.get_model()
    except AgentApiError as exc:
        if exc.status == 503:
            console.print("[dim]Model information is unavailable.[/dim]")
            return False
        raise
    return bool(document.get("vision"))


def _print_stage(console: Console, command: StageCommand) -> None:
    if not command.message:
        return
    if command.error:
        console.print(f"[red]{command.message}[/red]")
    elif command.dim:
        console.print(f"[dim]{command.message}[/dim]")
    else:
        console.print(command.message)


def _access_token(config: ServerConfig, console: Console) -> str | None:
    session = load_session()
    if session is None:
        console.print("Not signed in. Run [bold]ai-agent login[/bold].")
        return None
    if session_is_fresh(session):
        return session.access_token
    if not config.supabase_url.strip() or not config.supabase_publishable_key.strip():
        console.print("[red]The saved session expired. Run ai-agent login.[/red]")
        return None
    try:
        refreshed = refresh_session(
            supabase_url=config.supabase_url,
            anon_key=config.supabase_publishable_key,
            refresh_token=session.refresh_token,
        )
    except httpx.HTTPError:
        console.print("[red]Could not refresh sign-in. Run ai-agent login.[/red]")
        return None
    save_session(refreshed)
    return refreshed.access_token


def _apply_server_command(
    console: Console,
    current: ServerConfig,
    argument: str,
) -> ServerConfig | None:
    """Apply `/server`. Return None when the chat should stop so the user can sign in."""
    if not argument:
        console.print(current.server_url)
        console.print("[dim]Change it with /server https://agent.example.com[/dim]")
        return current
    try:
        update = set_server_url(argument)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return current
    except httpx.HTTPError as exc:
        console.print(f"[red]Could not reach that server:[/red] {exc}")
        return current
    if update.signed_out:
        console.print(f"Server URL updated to {update.config.server_url}.")
        console.print("Signed out. Run [bold]ai-agent login[/bold] to sign in again.")
        return None
    console.print(f"Server URL saved: {update.config.server_url}")
    return update.config


def _current_conversation(client: AgentApiClient, console: Console) -> str:
    saved = load_conversation_id()
    if saved:
        return saved
    rows = client.list_conversations()
    if rows:
        conversation_id = rows[0]["id"]
        title = rows[0].get("title") or "Untitled"
        save_conversation_id(conversation_id)
        console.print(f"[dim]Resuming {title}.[/dim]")
        return conversation_id
    created = client.create_conversation()
    save_conversation_id(created["id"])
    return created["id"]


def _print_access_error(console: Console, exc: AgentApiError) -> None:
    if exc.code in {ACCESS_PENDING_CODE, ACCESS_DENIED_CODE}:
        console.print(f"[yellow]{exc.detail}[/yellow]")
        if exc.code == ACCESS_PENDING_CODE:
            console.print(
                "[dim]An administrator must run on the server:\n"
                "  ai-agent config access list\n"
                "  ai-agent config access approve <your user id>[/dim]"
            )
        return
    if exc.status == 401:
        console.print("[red]Sign-in was rejected. Run ai-agent login.[/red]")
        return
    console.print(f"[red]{exc.detail}[/red]")


def _report_api_error(console: Console, exc: Exception, *, base_url: str) -> None:
    if isinstance(exc, AgentApiError):
        _print_access_error(console, exc)
        return
    if isinstance(exc, httpx.HTTPError):
        console.print(f"[red]Cannot reach {base_url}:[/red] {exc}")
        if hint := public_api_base_url_hint(base_url):
            console.print(f"[yellow]{hint}[/yellow]")
        return
    raise exc


def _create_conversation(
    client: AgentApiClient,
    console: Console,
) -> dict | None:
    try:
        return client.create_conversation()
    except (AgentApiError, httpx.HTTPError) as exc:
        _report_api_error(console, exc, base_url=client.base_url)
        return None


def _print_conversations(client: AgentApiClient, console: Console) -> bool:
    try:
        rows = client.list_conversations()
    except (AgentApiError, httpx.HTTPError) as exc:
        _report_api_error(console, exc, base_url=client.base_url)
        return False
    if not rows:
        console.print("[dim]No chats yet.[/dim]")
        return True
    current = load_conversation_id()
    for row in rows:
        mark = "*" if row.get("id") == current else " "
        title = row.get("title") or "Untitled"
        console.print(f"{mark} {title}  [dim]{row.get('id')}[/dim]")
    return True


def _play_turn(
    client: AgentApiClient,
    console: Console,
    conversation_id: str,
    content: str,
    images: list[ImageInput] | None = None,
) -> bool:
    started = False
    try:
        for event in client.stream_turn(conversation_id, content, images):
            kind = event.get("type")
            if kind == "token":
                text = event.get("text") or ""
                if not started:
                    console.print("[bold green]AI:[/bold green] ", end="")
                    started = True
                console.file.write(text)
                console.file.flush()
            elif kind == "notice":
                console.print(f"\n[dim]· {event.get('text', '')}[/dim]")
            elif kind == "status":
                console.print(f"[dim]{event.get('text', '')}[/dim]")
            elif kind == "approval_required":
                if started:
                    console.print()
                    started = False
                _answer_approval(client, console, conversation_id, event)
            elif kind == "done":
                if started:
                    console.print()
                error = event.get("error")
                if error and not event.get("message"):
                    console.print(f"[yellow]{error}[/yellow]")
                elif error:
                    console.print(f"\n[yellow]{error}[/yellow]")
            elif kind == "error":
                console.print(f"[red]{event.get('message', 'Turn failed.')}[/red]")
                return False
    except AgentApiError as exc:
        if exc.status == 401:
            console.print("[red]Sign-in was rejected. Run ai-agent login.[/red]")
        else:
            console.print(f"[red]{exc.detail}[/red]")
        return False
    except httpx.HTTPError as exc:
        console.print(f"[red]Lost the connection to the API:[/red] {exc}")
        return False
    return True


def _answer_approval(
    client: AgentApiClient,
    console: Console,
    conversation_id: str,
    event: dict,
) -> None:
    commands = event.get("commands") or []
    ordering = event.get("ordering") or "unordered"
    console.print("\n[bold]AI wants to execute:[/bold]")
    risks = []
    for index, command in enumerate(commands, start=1):
        risks.append(command.get("risk"))
        target = command.get("target")
        suffix = f"  [{target}]" if target else ""
        console.print(
            f"  {index}. {command.get('command')}  "
            f"[dim][{command.get('risk')}]{suffix}[/dim]"
        )
        reason = command.get("reason")
        if reason:
            console.print(f"     {reason}")
    if ordering == "ordered":
        console.print(
            "[dim]Ordered batch: rejecting a command also rejects every command below it.[/dim]"
        )
    elif ordering == "mixed":
        console.print(
            "[dim]Some commands are a sequence. Rejecting one also rejects "
            "later commands in that sequence.[/dim]"
        )
    allow_grant = bool(risks) and set(risks) <= {"READ_ONLY", "REVERSIBLE"}
    selectable = len(commands) > 1
    if selectable:
        console.print("[dim]s = choose which commands to run[/dim]")
    if allow_grant:
        console.print("[dim]a = allow this risk for the rest of the server session[/dim]")
        prompt = "\nApprove? (y/n/a/s) " if selectable else "\nApprove? (y/n/a) "
    else:
        prompt = "\nApprove? (y/n/s) " if selectable else "\nApprove? (y/n) "
    answer = input(prompt).strip().lower()
    if answer in {"s", "select"} and selectable:
        client.resolve_approval(
            conversation_id,
            event["approval_id"],
            decisions=_selected_decisions(console, commands),
        )
        return
    approved = answer in {"y", "yes", "a", "allow"}
    grant = None
    if answer in {"a", "allow"}:
        grant = "read_only_session" if set(risks) == {"READ_ONLY"} else "reversible_session"
    client.resolve_approval(
        conversation_id,
        event["approval_id"],
        approved=approved,
        grant_scope=grant,
    )


def _selected_decisions(console: Console, commands: list[dict]) -> list[dict]:
    """Ask y/n per command. An ordered rejection skips the rest of that sequence."""
    blocked: set[int] = set()
    decisions: list[dict] = []
    for index, command in enumerate(commands, start=1):
        group = command.get("order_group")
        rendered = command.get("command")
        if isinstance(group, int) and group in blocked:
            console.print(
                f"  {index}. {rendered}  "
                "[dim]rejected — an earlier command in this sequence was rejected[/dim]"
            )
            # Not an explicit rejection. The server applies the ordered rule.
            decisions.append({"id": index, "decision": "accept"})
            continue
        choice = input(f"  Run {index}. {rendered}? (y/n) ").strip().lower()
        accept = choice in {"y", "yes"}
        if not accept and isinstance(group, int):
            blocked.add(group)
        decisions.append({"id": index, "decision": "accept" if accept else "reject"})
    return decisions
