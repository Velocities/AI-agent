"""Text the bot shows. Discord delivery (embeds, mentions) lives in the bot."""

from __future__ import annotations

_PAGE = 4000


def pages(text: str, *, limit: int = _PAGE) -> list[str]:
    body = text.strip() or "(no reply)"
    return [body[index : index + limit] for index in range(0, len(body), limit)]


def explain_wait(ahead: int) -> str:
    if ahead == 1:
        who = "1 person is ahead of you."
    else:
        who = f"{ahead} people are ahead of you."
    return (
        f"Waiting for the model. {who} "
        "You will be pinged when your reply is ready."
    )


def explain_unreachable(url: str, exc: BaseException) -> str:
    from ai_agent_cli.api_url import public_api_base_url_hint

    lines = [f"Cannot reach {url}. That deployment is unreachable.", str(exc)]
    hint = public_api_base_url_hint(url)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def explain_api_error(exc) -> str:
    from ai_agent_cli.contracts import (
        ACCESS_DENIED_CODE,
        ACCESS_INCOMPLETE_CODE,
        ACCESS_PENDING_CODE,
    )

    if exc.code in {ACCESS_PENDING_CODE, ACCESS_DENIED_CODE, ACCESS_INCOMPLETE_CODE}:
        lines = [exc.detail]
        if exc.code == ACCESS_PENDING_CODE:
            lines.append(
                "An administrator must run on the server:\n"
                "  ai-agent config access list\n"
                "  ai-agent config access approve <your user id>"
            )
        return "\n\n".join(lines)
    if exc.status == 401:
        return "Sign-in was rejected. Run /login."
    return exc.detail or "The deployment rejected the request."


def format_approval(event: dict) -> str:
    commands = event.get("commands") or []
    ordering = event.get("ordering") or "unordered"
    lines = ["The agent wants to run:"]
    for index, command in enumerate(commands, start=1):
        if not isinstance(command, dict):
            continue
        target = command.get("target")
        suffix = f" [{target}]" if target else ""
        risk = command.get("risk") or ""
        lines.append(f"{index}. {command.get('command')} [{risk}]{suffix}")
        reason = command.get("reason")
        if reason:
            lines.append(f"   {reason}")
    if ordering == "ordered":
        lines.append("Ordered batch: rejecting a command also rejects every command below it.")
    elif ordering == "mixed":
        lines.append(
            "Some commands are a sequence. Rejecting one also rejects later commands in that sequence."
        )
    if len(commands) > 1:
        lines.append(
            "Choose commands in the menu, then Confirm. Approve runs all of them. Reject runs none."
        )
    return "\n".join(lines)


def approval_grant(commands: list[dict]) -> tuple[bool, str | None]:
    """Whether 'allow for this session' applies, and the grant name the API expects."""
    risks = [str(command.get("risk") or "") for command in commands if isinstance(command, dict)]
    if not risks or not set(risks) <= {"READ_ONLY", "REVERSIBLE"}:
        return False, None
    if set(risks) == {"READ_ONLY"}:
        return True, "read_only_session"
    return True, "reversible_session"


def decisions_for(commands: list[dict], accepted_ids: set[int]) -> list[dict]:
    """1-based accept/reject for every command. The API applies ordered cascades."""
    return [
        {"id": index, "decision": "accept" if index in accepted_ids else "reject"}
        for index, _command in enumerate(commands, start=1)
    ]
