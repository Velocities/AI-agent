from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from rich.console import Console

from ai_agent.config import Settings
from ai_agent.llm.server.process.base import EngineProcess, EngineProcessError
from ai_agent.llm.server.process.factory import create_engine_process


@contextmanager
def managed_engine_process(
    settings: Settings,
    console: Console,
) -> Iterator[EngineProcess]:
    process = create_engine_process(settings)
    label = process.engine_name
    try:
        with console.status(
            f"[bold cyan]Starting {label}[/bold cyan] "
            f"[dim]({settings.llm_upstream})[/dim]",
            spinner="dots",
        ):
            process.ensure_running(timeout=settings.llm_startup_timeout)
        if process.started_by_us:
            console.print(
                f"[green]✓[/green] Started {label} at [bold]{process.upstream_url}[/bold]"
            )
        yield process
    except EngineProcessError as exc:
        console.print(f"[red]Could not start inference engine:[/red] {exc}")
        raise
    finally:
        process.stop()
        if process.started_by_us:
            console.print(f"[dim]Stopped {label}.[/dim]")
