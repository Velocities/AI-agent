from __future__ import annotations

import os
import stat
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url

from ai_agent.config import Settings
from ai_agent.conversations.store import ConversationStore
from ai_agent.deployment.access_store import DeploymentAccessStore
from ai_agent.deployment.monitoring_admin_store import MonitoringAdminStore
from ai_agent.execution_targets.repository import UserExecutionTargetRepository

_APP_DATA = Path(".local") / "share" / "ai-agent"
_DB_NAME = "conversations.db"


def default_database_path() -> Path:
    """SQLite file on the machine running the model and ai-agent-serve."""
    return Path.home() / _APP_DATA / _DB_NAME


def shared_deployment_database_path() -> Path:
    """Shared DB for systemd installs (Linux) or the current user (Windows)."""
    if os.name == "posix":
        return Path("/var/lib/ai-agent") / _DB_NAME
    return default_database_path()


def service_user_database_path(service_user: str = "ai") -> Path:
    """Home of a named service account on Linux; current user on Windows."""
    home = _unix_account_home(service_user)
    if home is None:
        home = Path(f"/var/lib/{service_user}") if os.name == "posix" else Path.home()
    return home / _APP_DATA / _DB_NAME


def _unix_account_home(username: str) -> Path | None:
    if os.name != "posix":
        return None
    try:
        import pwd

        return Path(pwd.getpwnam(username).pw_dir)
    except KeyError:
        return None


def service_user_database_url(service_user: str = "ai") -> str:
    return f"sqlite:///{service_user_database_path(service_user)}"


def shared_deployment_database_url() -> str:
    return f"sqlite:///{shared_deployment_database_path()}"


def database_url(settings: Settings) -> str:
    configured = settings.conversation_database.strip()
    if configured:
        return configured
    path = default_database_path()
    _ensure_private_dir(path.parent)
    return f"sqlite:///{path}"


def deployment_database_url(settings: Settings) -> str:
    """SQLite URL used by `ai-agent serve` on this host.

    Reads ``CONVERSATION_DATABASE`` from settings (``.env`` in the service
    WorkingDirectory). When unset, uses the shared ``StateDirectory`` file under
    ``/var/lib/ai-agent/conversations.db`` on Linux — or the current user's
    app data directory on Windows.
    """
    configured = settings.conversation_database.strip()
    if configured:
        return configured
    return shared_deployment_database_url()


def database_url_for_admin_cli(settings: Settings, *, service_db: bool) -> str:
    """Pick the database for ``config access``, ``config monitoring``, and ``execution-target``."""
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
) -> tuple[
    ConversationStore,
    DeploymentAccessStore,
    UserExecutionTargetRepository,
    MonitoringAdminStore,
]:
    url = database_url(settings)
    upgrade_database(url)
    engine = _engine(url)
    _restrict_sqlite_file(url)
    return _stores(engine)


def open_store_at(url: str) -> ConversationStore:
    """Open a store at an explicit URL. Used by tests and by open_store."""
    return open_stores_at(url)[0]


def open_stores_at(
    url: str,
) -> tuple[
    ConversationStore,
    DeploymentAccessStore,
    UserExecutionTargetRepository,
    MonitoringAdminStore,
]:
    upgrade_database(url)
    engine = _engine(url)
    return _stores(engine)


def _stores(
    engine: Engine,
) -> tuple[
    ConversationStore,
    DeploymentAccessStore,
    UserExecutionTargetRepository,
    MonitoringAdminStore,
]:
    return (
        ConversationStore(engine),
        DeploymentAccessStore(engine),
        UserExecutionTargetRepository(engine),
        MonitoringAdminStore(engine),
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


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "posix":
        return
    path.chmod(stat.S_IRWXU)


def _shared_sqlite_file_mode() -> int:
    return stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP


def _restrict_sqlite_file(url: str) -> None:
    if os.name != "posix":
        return
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