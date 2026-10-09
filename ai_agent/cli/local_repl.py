"""In-process interactive chat on the server (not the default `ai-agent` command).

Planned v2: compose this with the same agent/target paths as ai-agent serve
instead of global YAML. See docs/local-in-process-chat.md.
"""

from __future__ import annotations

from rich.console import Console

from ai_agent.agent.factory import (
    build_agent,
    configure_logging,
    configure_stdio_encoding,
    present_turn_result,
    warmup_agent,
)
from ai_agent.config import Settings
from ai_agent.llm.streaming import sanitize_terminal_text


def run_repl() -> int:
    """In-process REPL. The `ai-agent` command uses the remote client instead."""
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
