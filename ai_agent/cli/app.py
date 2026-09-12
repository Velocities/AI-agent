from __future__ import annotations

import logging
import os
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
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.execution_targets.router import load_router
from ai_agent.execution_targets.store import TargetConfigError
from ai_agent.llm import create_llm_provider
from ai_agent.llm.streaming import sanitize_terminal_text
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
            "Answer stopped early after repeated cutoffs. Raise OLLAMA_NUM_CTX or "
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


def build_agent(console: Console | None = None) -> AgentLoop:
    settings = Settings()
    configure_logging(settings.agent_log_level)
    console = console or Console()

    policy = PolicyEngine.from_yaml(settings.policy_path(), settings.agent_scratch_dir)
    executor = CommandExecutor(
        timeout=settings.agent_tool_timeout,
        output_limit=settings.agent_output_limit,
        scratch_dir=settings.agent_scratch_dir,
    )
    try:
        router = load_router(
            executor,
            settings.agent_execution_targets_file,
            default_override=os.environ.get("AGENT_DEFAULT_TARGET"),
        )
    except TargetConfigError as exc:
        console.print(f"[red]Invalid execution target config:[/red] {exc}")
        raise
    audit_path = Path(settings.agent_audit_log) if settings.agent_audit_log else None
    audit = AuditLogger(log_path=audit_path, user=getuser())
    session = ApprovalSession()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, console)
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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] == "config":
        from ai_agent.cli.config_cmd import main as config_main

        return config_main(args[1:])
    if args and args[0] == "host-setup":
        from ai_agent.cli.host_setup import main as host_setup_main

        return host_setup_main(args[1:])
    return run_repl()


def run_repl() -> int:
    configure_stdio_encoding()
    console = Console()
    settings = Settings()
    configure_logging(settings.agent_log_level)

    console.print("[bold]AI Server Assistant[/bold]")
    agent = build_agent(console)
    engine_label = agent.llm.engine_name or "LLM server"
    model_label = agent.llm.model_name or settings.llm_model
    console.print(
        f"Engine: {engine_label} | Model: {model_label} @ "
        f"{agent.llm.endpoint or settings.llm_host} | "
        f"Confirmation: {settings.agent_confirmation_mode.value}"
    )
    target_names = ", ".join(agent.router.names())
    console.print(
        f"Execution targets: {target_names} "
        f"(default: {agent.router.default_name})"
    )
    console.print("Type 'exit' or 'quit' to leave.\n")

    try:
        if not warmup_agent(agent, console):
            return 1

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

            console.print()
            streamed = False
            status = console.status("[dim]Thinking...[/dim]", spinner="dots")
            status.start()

            def on_stream_chunk(text: str) -> None:
                nonlocal streamed
                safe_text = sanitize_terminal_text(text)
                if not safe_text:
                    return
                if not streamed:
                    status.stop()
                    console.print("[bold green]AI:[/bold green] ", end="")
                    streamed = True
                console.file.write(safe_text)
                console.file.flush()

            def on_iteration(iteration: int) -> None:
                if iteration > 1 and not streamed:
                    status.update(f"[dim]Working (step {iteration})...[/dim]")

            def on_notice(text: str) -> None:
                if streamed:
                    return
                status.stop()
                console.print(f"[dim]· {text}[/dim]")
                status.start()

            try:
                result = agent.run(
                    user_input,
                    stream_callback=on_stream_chunk,
                    iteration_callback=on_iteration,
                    notice_callback=on_notice,
                )
            finally:
                status.stop()

            if present_turn_result(console, result, streamed=streamed):
                return 1
            console.print()
    finally:
        agent.llm.close()


if __name__ == "__main__":
    raise SystemExit(main())
