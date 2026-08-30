from __future__ import annotations

import logging

from rich.console import Console

from ai_agent.agent.context import build_system_prompt, gather_runtime_context
from ai_agent.agent.warmup import warmup_llm
from ai_agent.cli.app import configure_logging, configure_stdio_encoding
from ai_agent.cli.errors import startup_should_exit
from ai_agent.config import LlmTransport, Settings
from ai_agent.llm.base import LLMProvider
from ai_agent.llm.factory import create_http_session, create_llm_provider
from ai_agent.llm.server import LlmFacade, bind_llm_server, public_url
from ai_agent.llm.session import LlmHttpSession
from ai_agent.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


def _system_prompt(settings: Settings) -> str:
    policy = PolicyEngine.from_yaml(settings.policy_path(), settings.agent_scratch_dir)
    runtime = gather_runtime_context(settings)
    return build_system_prompt(runtime, policy.allowed_binaries())


def prepare_upstream(
    settings: Settings,
    console: Console,
) -> tuple[LLMProvider, LlmHttpSession] | None:
    if settings.ollama_transport == LlmTransport.SSH:
        session = create_http_session(settings)
    else:
        session = create_http_session(settings, base_url=settings.ollama_upstream)
    provider = create_llm_provider(settings, session=session)
    health = provider.healthcheck()
    if not health.ok:
        logger.error("LLM healthcheck failed: %s", health.message)
        console.print(f"[red]LLM endpoint unavailable:[/red] {health.message}")
        provider.close()
        return None

    with console.status(
        f"[bold cyan]Loading {settings.ollama_model}[/bold cyan] "
        "[dim](warming up GPU with agent context)[/dim]",
        spinner="dots",
    ):
        ok, detail, duration = warmup_llm(provider, _system_prompt(settings))

    if not ok:
        logger.error("Model warmup failed: %s", detail)
        console.print(f"[red]LLM warmup failed:[/red] {detail}")
        provider.close()
        return None

    console.print(
        f"[green]✓[/green] Model ready in [bold]{duration:.1f}s[/bold] "
        "[dim](system prompt + tools loaded)[/dim]"
    )
    return provider, session


def serve_ready_provider(
    provider: LLMProvider,
    session: LlmHttpSession,
    settings: Settings,
    console: Console,
) -> int:
    facade = LlmFacade(session)
    httpd = bind_llm_server(settings.llm_bind_host, settings.llm_bind_port, facade)
    host, port = httpd.server_address[:2]
    endpoint = public_url(str(host), int(port))
    console.print(f"Upstream: {session.base_url}")
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
        provider.close()
    return 0


def main() -> int:
    configure_stdio_encoding()
    console = Console()
    settings = Settings()
    configure_logging(settings.agent_log_level)

    console.print("[bold]AI Agent LLM[/bold]")
    console.print(
        f"Model: {settings.ollama_model} @ {settings.ollama_upstream} "
        f"(upstream, independent of OLLAMA_HOST)\n"
    )

    prepared = prepare_upstream(settings, console)
    if prepared is None:
        return 1 if startup_should_exit(healthy=False, warmup_ok=False) else 0
    provider, session = prepared
    return serve_ready_provider(provider, session, settings, console)


if __name__ == "__main__":
    raise SystemExit(main())
