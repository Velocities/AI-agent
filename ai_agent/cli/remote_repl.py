from __future__ import annotations

import httpx
from rich.console import Console

from ai_agent.deployment.access import ACCESS_DENIED_CODE, ACCESS_PENDING_CODE
from ai_agent.cli.api_client import AgentApiClient, AgentApiError
from ai_agent.cli.api_url import public_api_base_url_hint
from ai_agent.cli.credentials import (
    load_conversation_id,
    load_session,
    save_conversation_id,
    save_session,
    session_is_fresh,
)
from ai_agent.cli.login import refresh_session
from ai_agent.config import Settings


def run_remote_repl() -> int:
    console = Console()
    settings = Settings()
    token = _access_token(settings, console)
    if token is None:
        return 1

    client = AgentApiClient(settings.api_base_url, token)
    try:
        conversation_id = _current_conversation(client, console)
    except AgentApiError as exc:
        _print_access_error(console, exc)
        client.close()
        return 1
    except httpx.HTTPError as exc:
        console.print(f"[red]Cannot reach {settings.api_base_url}:[/red] {exc}")
        console.print(
            "Start [bold]ai-agent serve[/bold] on the model machine and try again."
        )
        client.close()
        return 1

    console.print("[bold]AI Server Assistant[/bold]")
    console.print(f"API: {settings.api_base_url}")
    if hint := public_api_base_url_hint(settings.api_base_url):
        console.print(f"[yellow]{hint}[/yellow]")
    console.print("Type /new, /list, or exit.\n")

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
                console.print("Goodbye.")
                return 0
            if user_input == "/list":
                if not _print_conversations(client, console):
                    return 1
                continue
            if user_input == "/new":
                created = _create_conversation(client, console)
                if created is None:
                    return 1
                conversation_id = created["id"]
                save_conversation_id(conversation_id)
                console.print("[dim]Started a new chat.[/dim]")
                continue
            if not _play_turn(client, console, conversation_id, user_input):
                return 1
            console.print()
    finally:
        client.close()


def _access_token(settings: Settings, console: Console) -> str | None:
    session = load_session()
    if session is None:
        console.print("Not signed in. Run [bold]ai-agent login[/bold].")
        return None
    if session_is_fresh(session):
        return session.access_token
    if not settings.supabase_url.strip() or not settings.supabase_anon_key.strip():
        console.print("[red]The saved session expired. Run ai-agent login.[/red]")
        return None
    try:
        refreshed = refresh_session(
            supabase_url=settings.supabase_url,
            anon_key=settings.supabase_anon_key,
            refresh_token=session.refresh_token,
        )
    except httpx.HTTPError:
        console.print("[red]Could not refresh sign-in. Run ai-agent login.[/red]")
        return None
    save_session(refreshed)
    return refreshed.access_token


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
) -> bool:
    started = False
    try:
        for event in client.stream_turn(conversation_id, content):
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
    allow_grant = bool(risks) and set(risks) <= {"READ_ONLY", "REVERSIBLE"}
    prompt = "\nApprove? (y/n/a) " if allow_grant else "\nApprove? (y/n) "
    if allow_grant:
        console.print("[dim]a = allow this risk for the rest of the server session[/dim]")
    answer = input(prompt).strip().lower()
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
