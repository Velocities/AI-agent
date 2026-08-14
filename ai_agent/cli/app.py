from __future__ import annotations

import logging
import os
import sys
from getpass import getuser
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from ai_agent.agent.loop import AgentLoop
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.llm.ollama import OllamaProvider
from ai_agent.policy.engine import PolicyEngine


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


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
    audit_path = Path(settings.agent_audit_log) if settings.agent_audit_log else None
    audit = AuditLogger(log_path=audit_path, user=getuser())
    session = ApprovalSession()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, console)
    llm = OllamaProvider(settings.ollama_host, settings.ollama_model)

    return AgentLoop(
        settings=settings,
        llm=llm,
        policy=policy,
        executor=executor,
        audit=audit,
        prompter=prompter,
        session=session,
    )


def main() -> None:
    console = Console()
    settings = Settings()
    configure_logging(settings.agent_log_level)

    console.print("[bold]AI Server Assistant[/bold]")
    console.print(
        f"Model: {settings.ollama_model} @ {settings.ollama_host} | "
        f"Confirmation: {settings.agent_confirmation_mode.value}"
    )
    console.print("Type 'exit' or 'quit' to leave.\n")

    llm = OllamaProvider(settings.ollama_host, settings.ollama_model)
    healthy, message = llm.healthcheck()
    if not healthy:
        console.print(f"[yellow]Warning:[/yellow] {message}")

    agent = build_agent(console)

    while True:
        try:
            user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            console.print("Goodbye.")
            break

        result = agent.run(user_input)
        console.print()
        console.print("[bold green]AI:[/bold green]")
        console.print(Markdown(result.final_message))
        if result.error == "max_iterations":
            console.print("[yellow]Agent stopped at iteration limit.[/yellow]")
        console.print()


if __name__ == "__main__":
    main()
