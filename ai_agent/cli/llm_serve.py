from __future__ import annotations

import logging

from rich.console import Console

from ai_agent.agent.context import build_system_prompt, gather_runtime_context
from ai_agent.cli.app import configure_logging, configure_stdio_encoding
from ai_agent.cli.errors import startup_should_exit
from ai_agent.config import Settings
from ai_agent.llm.server.engine.base import LlmEngine
from ai_agent.llm.server.facade import AgentLlmFacade, bind_llm_server, public_url
from ai_agent.llm.server.factory import create_engine
from ai_agent.llm.server.warmup import warmup_engine
from ai_agent.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


def _system_prompt(settings: Settings) -> str:
    policy = PolicyEngine.from_yaml(settings.policy_path(), settings.agent_scratch_dir)
    runtime = gather_runtime_context(settings)
    return build_system_prompt(runtime, policy.allowed_binaries())


def prepare_upstream(
    settings: Settings,
    console: Console,
) -> LlmEngine | None:
    engine = create_engine(settings)
    health = engine.healthcheck()
    if not health.ok:
        logger.error("LLM healthcheck failed: %s", health.message)
        console.print(f"[red]LLM endpoint unavailable:[/red] {health.message}")
        engine.close()
        return None

    with console.status(
        f"[bold cyan]Loading {engine.model}[/bold cyan] "
        f"[dim]({engine.engine_name}, warming up GPU with agent context)[/dim]",
        spinner="dots",
    ):
        ok, detail, duration = warmup_engine(engine, _system_prompt(settings))

    if not ok:
        logger.error("Model warmup failed: %s", detail)
        console.print(f"[red]LLM warmup failed:[/red] {detail}")
        engine.close()
        return None

    console.print(
        f"[green]✓[/green] {engine.engine_name} ready in [bold]{duration:.1f}s[/bold] "
        "[dim](system prompt + tools loaded)[/dim]"
    )
    return engine


def serve_ready_engine(
    engine: LlmEngine,
    settings: Settings,
    console: Console,
) -> int:
    facade = AgentLlmFacade(engine)
    httpd = bind_llm_server(settings.llm_bind_host, settings.llm_bind_port, facade)
    host, port = httpd.server_address[:2]
    endpoint = public_url(str(host), int(port))
    console.print(f"Engine: {engine.engine_name}")
    console.print(f"Upstream: {engine.upstream_url}")
    console.print(f"[bold]Endpoint:[/bold] {endpoint}\n")
    console.print("Copy this into .env, then start [bold]ai-agent[/bold] in another terminal:")
    console.print(f"  OLLAMA_HOST={endpoint}")
    console.print("\n[dim]Leave this window open. Ctrl+C to stop.[/dim]\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("\nStopping LLM facade.")
    finally:
        httpd.server_close()
        engine.close()
    return 0


def main() -> int:
    configure_stdio_encoding()
    console = Console()
    settings = Settings()
    configure_logging(settings.agent_log_level)

    console.print("[bold]AI Agent LLM[/bold]")
    console.print(
        f"Engine: {settings.llm_engine.value} | "
        f"Model: {settings.llm_model} @ {settings.llm_upstream_url()}\n"
    )

    engine = prepare_upstream(settings, console)
    if engine is None:
        return 1 if startup_should_exit(healthy=False, warmup_ok=False) else 0
    return serve_ready_engine(engine, settings, console)


if __name__ == "__main__":
    raise SystemExit(main())
