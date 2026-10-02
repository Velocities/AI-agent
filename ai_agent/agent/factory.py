from __future__ import annotations

import logging
import sys
from getpass import getuser
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from ai_agent.agent.loop import AgentLoop, AgentRunResult
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.cli.errors import startup_should_exit, turn_should_exit
from ai_agent.commands.run_as import build_command_executor
from ai_agent.config import Settings
from ai_agent.deployment.access import AccessStatus
from ai_agent.deployment.access_store import DeploymentAccessStore
from ai_agent.execution_targets.build_router import build_router_for_user
from ai_agent.execution_targets.repository import UserExecutionTargetRepository
from ai_agent.execution_targets.router import ExecutionTargetRouter
from ai_agent.execution_targets.secure_key_store import OSSecureKeyStore, SecureKeyStore
from ai_agent.execution_targets.store import TargetConfigError
from ai_agent.llm import create_llm_provider
from ai_agent.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


def configure_stdio_encoding() -> None:
    """Keep terminal output alive on consoles that cannot encode UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            logger.debug("Could not switch %s to UTF-8", stream, exc_info=True)


def run_error_notice(error: str | None) -> str | None:
    """Short status line for a run that did not finish cleanly."""
    if not error:
        return None
    if error == "max_iterations":
        return "Agent stopped at the tool iteration limit."
    if error == "truncated":
        return (
            "Answer stopped early after repeated cutoffs. Raise OLLAMA_NUM_CTX (Ollama) or "
            "AGENT_MAX_CONTINUATIONS, or ask for a smaller piece at a time."
        )
    if error == "empty_response":
        return "The model returned no answer."
    return f"LLM error: {error}"


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_agent(
    console: Console | None = None,
    *,
    prompter=None,
    audit_user: str | None = None,
    session: ApprovalSession | None = None,
    settings: Settings | None = None,
    run_as_linux_user: str | None = None,
    user_id: str | None = None,
    target_repo: UserExecutionTargetRepository | None = None,
    access_store: DeploymentAccessStore | None = None,
    key_store: SecureKeyStore | None = None,
) -> AgentLoop:
    settings = settings or Settings()
    configure_logging(settings.agent_log_level)
    console = console or Console()

    policy = PolicyEngine.from_yaml(settings.policy_path(), settings.agent_scratch_dir)
    executor = build_command_executor(
        timeout=settings.agent_tool_timeout,
        output_limit=settings.agent_output_limit,
        scratch_dir=settings.agent_scratch_dir,
        linux_username=run_as_linux_user,
    )
    try:
        router = _build_router(
            executor=executor,
            user_id=user_id,
            target_repo=target_repo,
            access_store=access_store,
            key_store=key_store,
        )
    except TargetConfigError as exc:
        console.print(f"[red]Invalid execution target config:[/red] {exc}")
        raise
    if session is None:
        session = getattr(prompter, "session", None) or ApprovalSession()
    if prompter is None:
        prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, console)
    audit_path = Path(settings.agent_audit_log) if settings.agent_audit_log else None
    audit = AuditLogger(log_path=audit_path, user=audit_user or getuser())
    llm = create_llm_provider(settings)

    return AgentLoop(
        settings=settings,
        llm=llm,
        policy=policy,
        executor=executor,
        audit=audit,
        prompter=prompter,
        session=session,
        router=router,
    )


def _build_router(
    *,
    executor,
    user_id: str | None,
    target_repo: UserExecutionTargetRepository | None,
    access_store: DeploymentAccessStore | None,
    key_store: SecureKeyStore | None,
) -> ExecutionTargetRouter:
    if user_id and target_repo is not None and access_store is not None:
        record = access_store.get(user_id)
        if record is None or record.status != AccessStatus.APPROVED:
            raise TargetConfigError("User is not approved for command execution.")
        linux = record.linux_username.strip()
        if not linux:
            raise TargetConfigError(
                "Linux username is required. Approve with: "
                "ai-agent config access approve <user_id> --run-as <linux_user>"
            )
        store = key_store or OSSecureKeyStore()
        return build_router_for_user(
            user_id=user_id,
            linux_username=linux,
            executor=executor,
            target_repo=target_repo,
            key_store=store,
        )
    return ExecutionTargetRouter.local_only(executor)


def warmup_agent(agent: AgentLoop, console: Console) -> bool:
    health = agent.llm.healthcheck()
    if not health.ok:
        logger.error("LLM healthcheck failed: %s", health.message)
        console.print(f"[red]LLM endpoint unavailable:[/red] {health.message}")
        return not startup_should_exit(healthy=False, warmup_ok=True)

    model_label = agent.llm.model_name or agent.settings.llm_model
    engine_label = agent.llm.engine_name or "LLM server"
    with console.status(
        f"[bold cyan]Loading {model_label}[/bold cyan] "
        f"[dim]({engine_label}, warming up GPU with agent context)[/dim]",
        spinner="dots",
    ):
        ok, detail, duration = agent.warmup()

    if ok:
        console.print(
            f"[green]✓[/green] Model ready in [bold]{duration:.1f}s[/bold] "
            "[dim](system prompt + tools loaded)[/dim]\n"
        )
        return True

    logger.error("Model warmup failed: %s", detail)
    console.print(f"[red]LLM warmup failed:[/red] {detail}")
    return not startup_should_exit(healthy=True, warmup_ok=False)


def present_turn_result(
    console: Console,
    result: AgentRunResult,
    *,
    streamed: bool,
) -> bool:
    """Show the turn outcome. Return True when the process should exit."""
    if result.error:
        logger.warning(
            "Turn ended with error (%s): %s",
            result.error_kind.value if result.error_kind else "none",
            result.error,
        )

    if streamed:
        console.print()
    else:
        console.print("[bold green]AI:[/bold green]")
        console.print(Markdown(result.final_message))

    if turn_should_exit(result.error_kind):
        logger.error("LLM session closed: %s", result.error)
        console.print(
            f"[red]{result.error or 'LLM session is gone.'}[/red] Exiting."
        )
        return True

    if streamed or result.error in {"max_iterations", "truncated"}:
        notice = run_error_notice(result.error)
        if notice:
            console.print(f"[yellow]{notice}[/yellow]")
    return False
