from __future__ import annotations

import logging
import signal
import threading

import uvicorn
from rich.console import Console

from ai_agent.api.app import create_app
from ai_agent.api.serve import PublicBindError, assert_loopback_bind
from ai_agent.cli.app import configure_logging, configure_stdio_encoding
from ai_agent.cli.errors import startup_should_exit
from ai_agent.cli.llm_serve import prepare_upstream
from ai_agent.config import LlmTransport, Settings
from ai_agent.conversations.db import database_display_path, database_url, open_store
from ai_agent.llm.server.facade import AgentLlmFacade, bind_llm_server, public_url
from ai_agent.llm.server.process.base import EngineProcessError
from ai_agent.llm.server.runtime import managed_engine_process
from ai_agent.service.notify import sd_notify

logger = logging.getLogger(__name__)


def settings_for_api(settings: Settings, facade_url: str) -> Settings:
    """Point the API at the facade this process just bound.

    The chat client still uses API_BASE_URL. LLM_HOST in the environment is
    left unchanged on disk; only this process's API settings change. Transport
    is HTTP because the facade is local even when the engine itself is reached
    over SSH.
    """
    return settings.model_copy(
        update={
            "llm_host": facade_url,
            "llm_transport": LlmTransport.HTTP,
        }
    )


class _ApiServer(uvicorn.Server):
    """Notify systemd only after the listen socket exists."""

    def __init__(self, config: uvicorn.Config, on_listening) -> None:
        super().__init__(config)
        self._on_listening = on_listening

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self._on_listening()


def _install_shutdown_signals() -> None:
    """Turn terminal and systemd signals into a normal exit during startup.

    uvicorn replaces these handlers while it is serving, then restores them.
    Exit 0 on SIGTERM so systemd does not treat a stop as a crash.
    """

    def _handle(signum: int, _frame) -> None:
        if signum == signal.SIGINT:
            raise SystemExit(130)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def _facade_loop(httpd) -> None:
    try:
        httpd.serve_forever(poll_interval=0.5)
    except Exception:
        logger.exception("LLM facade stopped unexpectedly")


def _stop_facade(httpd, thread: threading.Thread) -> None:
    """Stop the facade without deadlocking if it has not entered serve_forever.

    BaseServer.shutdown waits until serve_forever is inside its loop. Closing
    the socket unblocks that loop, and the stopper thread is a daemon so a
    missed handshake cannot pin the process.
    """
    stopper = threading.Thread(
        target=httpd.shutdown,
        name="llm-facade-stop",
        daemon=True,
    )
    stopper.start()
    stopper.join(timeout=5)
    if stopper.is_alive():
        logger.warning("LLM facade did not acknowledge shutdown; closing the socket")
    httpd.server_close()
    thread.join(timeout=5)
    if thread.is_alive():
        logger.warning("LLM facade thread did not exit within 5s")


def _run_api(settings: Settings, store, console: Console) -> int:
    host = settings.api_bind_host.strip()
    port = settings.api_bind_port
    display = "127.0.0.1" if host.lower() == "localhost" else host
    app = create_app(settings, store=store)
    listening = f"http://{display}:{port}"
    logger.info("API listening at %s", listening)
    console.print(f"[bold]API:[/bold] {listening}")
    if settings.supabase_url.strip():
        console.print("Auth: Supabase access token")
    else:
        console.print("[yellow]Auth: not configured[/yellow] (set SUPABASE_URL)")
    console.print(f"Conversations: {database_display_path(database_url(settings))}")
    console.print(f"Model: {settings.llm_host}")
    console.print("\n[dim]Ctrl+C to stop. Logs go to stderr.[/dim]\n")

    def on_listening() -> None:
        sd_notify(f"Listening on {listening}", ready=True)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=settings.agent_log_level.lower(),
        timeout_graceful_shutdown=10,
    )
    _ApiServer(config, on_listening).run()
    return 0


def _serve_with_engine(settings: Settings, console: Console, store, process) -> int:
    sd_notify(f"Warming {settings.llm_model}")
    engine = prepare_upstream(
        settings,
        console,
        upstream_url=process.upstream_url,
    )
    if engine is None:
        return 1 if startup_should_exit(healthy=False, warmup_ok=False) else 0

    try:
        httpd = bind_llm_server(
            settings.llm_bind_host,
            settings.llm_bind_port,
            AgentLlmFacade(engine),
        )
    except OSError as exc:
        logger.error(
            "Could not bind the LLM facade on %s:%s: %s",
            settings.llm_bind_host,
            settings.llm_bind_port,
            exc,
        )
        console.print(f"[red]Could not bind the LLM facade:[/red] {exc}")
        engine.close()
        return 1

    host, port = httpd.server_address[:2]
    endpoint = public_url(str(host), int(port))
    logger.info(
        "LLM facade at %s (upstream %s)",
        endpoint,
        engine.upstream_url,
    )
    console.print(f"[bold]LLM facade:[/bold] {endpoint}")
    console.print(f"Upstream: {engine.upstream_url}")

    thread = threading.Thread(
        target=_facade_loop,
        args=(httpd,),
        name="llm-facade",
        daemon=True,
    )
    thread.start()
    api_settings = settings_for_api(settings, endpoint)
    try:
        return _run_api(api_settings, store, console)
    finally:
        sd_notify("Stopping", stopping=True)
        logger.info("Stopping LLM facade")
        _stop_facade(httpd, thread)
        engine.close()


def run(settings: Settings, console: Console) -> int:
    """Start the engine, the LLM facade, and the API. Block until shutdown."""
    try:
        assert_loopback_bind(settings.api_bind_host, settings.api_bind_port)
    except PublicBindError as exc:
        logger.error("%s", exc)
        console.print(f"[red]{exc}[/red]")
        return 1

    if not settings.supabase_url.strip():
        logger.warning(
            "SUPABASE_URL is unset. /health will answer, /api/me will return 503."
        )

    sd_notify("Opening conversation database")
    try:
        store = open_store(settings)
    except Exception as exc:
        logger.error("Could not open conversation database: %s", exc)
        console.print(f"[red]Could not open conversation database:[/red] {exc}")
        return 1

    sd_notify(f"Starting {settings.llm_engine.value}")
    try:
        with managed_engine_process(settings, console) as process:
            return _serve_with_engine(settings, console, store, process)
    except EngineProcessError:
        return 1 if startup_should_exit(healthy=False, warmup_ok=False) else 0


def main() -> int:
    configure_stdio_encoding()
    console = Console(stderr=True)
    settings = Settings()
    configure_logging(settings.agent_log_level)
    _install_shutdown_signals()

    console.print("[bold]AI Agent[/bold]")
    console.print(
        f"Engine: {settings.llm_engine.value} | "
        f"Model: {settings.llm_model} @ {settings.llm_upstream}"
    )
    console.print(
        f"API: http://{settings.api_bind_host}:{settings.api_bind_port}\n"
    )
    try:
        return run(settings, console)
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130
    except SystemExit as exc:
        code = exc.code
        if code is None or code == 0:
            logger.info("Shutdown requested")
            return 0
        if isinstance(code, int):
            if code == 130:
                logger.info("Interrupted")
            else:
                logger.error("Exiting with status %s", code)
            return code
        logger.error("%s", code)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
