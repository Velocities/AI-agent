from __future__ import annotations

import pwd
import stat
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url

from ai_agent.config import Settings
from ai_agent.conversations.store import ConversationStore
from ai_agent.deployment.access_store import DeploymentAccessStore
from ai_agent.execution_targets.repository import UserExecutionTargetRepository


def default_database_path() -> Path:
    """SQLite file on the machine running the model and ai-agent-serve."""
    return Path.home() / ".local" / "share" / "ai-agent" / "conversations.db"


def shared_deployment_database_path() -> Path:
    """Single SQLite file for systemd + admin CLI (see CONVERSATION_DATABASE).

    Must stay under the unit's StateDirectory=ai-agent; ProtectSystem=strict
    makes the rest of /var/lib read-only for the service.
    """
    return Path("/var/lib/ai-agent") / "conversations.db"


def service_user_database_path(service_user: str = "ai") -> Path:
    """Where the API stores data when CONVERSATION_DATABASE is unset and User=ai."""
    try:
        home = Path(pwd.getpwnam(service_user).pw_dir)
    except KeyError:
        home = Path(f"/var/lib/{service_user}")
    return home / ".local" / "share" / "ai-agent" / "conversations.db"


def service_user_database_url(service_user: str = "ai") -> str:
    return f"sqlite:///{service_user_database_path(service_user)}"


def shared_deployment_database_url() -> str:
    return f"sqlite:///{shared_deployment_database_path()}"


def database_url(settings: Settings) -> str:
    configured = settings.conversation_database.strip()
    if configured:
        return configured
    path = default_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(stat.S_IRWXU)
    return f"sqlite:///{path}"


def deployment_database_url(settings: Settings) -> str:
    """SQLite URL used by `ai-agent serve` on this host.

    Reads ``CONVERSATION_DATABASE`` from settings (``.env`` in the service
    WorkingDirectory). When unset, uses the shared ``StateDirectory`` file under
    ``/var/lib/ai-agent/conversations.db`` — not the service user's
    ``~/.local/share/...`` path.
    """
    configured = settings.conversation_database.strip()
    if configured:
        return configured
    return shared_deployment_database_url()


def database_url_for_admin_cli(settings: Settings, *, service_db: bool) -> str:
    """Pick the database for server-side ``config access`` / ``execution-target``."""
    if service_db:
        return deployment_database_url(settings)
    return database_url(settings)


def database_display_path(url: str) -> str:
    made = make_url(url)
    if made.drivername.startswith("sqlite") and made.database:
        return made.database
    return made.render_as_string(hide_password=True)


def upgrade_database(url: str) -> None:
    root = Path(__file__).resolve().parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def open_store(settings: Settings) -> ConversationStore:
    return open_stores(settings)[0]


def open_stores(
    settings: Settings,
) -> tuple[ConversationStore, DeploymentAccessStore, UserExecutionTargetRepository]:
    url = database_url(settings)
    upgrade_database(url)
    engine = _engine(url)
    _restrict_sqlite_file(url)
    return (
        ConversationStore(engine),
        DeploymentAccessStore(engine),
        UserExecutionTargetRepository(engine),
    )


def open_store_at(url: str) -> ConversationStore:
    """Open a store at an explicit URL. Used by tests and by open_store."""
    return open_stores_at(url)[0]


def open_stores_at(
    url: str,
) -> tuple[ConversationStore, DeploymentAccessStore, UserExecutionTargetRepository]:
    upgrade_database(url)
    engine = _engine(url)
    return (
        ConversationStore(engine),
        DeploymentAccessStore(engine),
        UserExecutionTargetRepository(engine),
    )


def _engine(url: str) -> Engine:
    from sqlalchemy import create_engine

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        _enable_sqlite(engine)
    return engine


def _enable_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        cursor.close()


def _shared_sqlite_file_mode() -> int:
    return stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP


def _restrict_sqlite_file(url: str) -> None:
    made = make_url(url)
    if not made.drivername.startswith("sqlite") or not made.database:
        return
    if made.database == ":memory:":
        return
    path = Path(made.database)
    if not path.exists():
        return
    if path.resolve() == shared_deployment_database_path().resolve():
        path.chmod(_shared_sqlite_file_mode())
        _restrict_shared_sqlite_sidecars(path)
        return
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _restrict_shared_sqlite_sidecars(db_path: Path) -> None:
    mode = _shared_sqlite_file_mode()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{db_path}{suffix}")
        if sidecar.exists():
            sidecar.chmod(mode)
