from __future__ import annotations

import stat
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url

from ai_agent.config import Settings
from ai_agent.conversations.store import ConversationStore
from ai_agent.deployment.access_store import DeploymentAccessStore


def default_database_path() -> Path:
    """SQLite file on the machine running the model and ai-agent-serve."""
    return Path.home() / ".local" / "share" / "ai-agent" / "conversations.db"


def database_url(settings: Settings) -> str:
    configured = settings.conversation_database.strip()
    if configured:
        return configured
    path = default_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(stat.S_IRWXU)
    return f"sqlite:///{path}"


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


def open_stores(settings: Settings) -> tuple[ConversationStore, DeploymentAccessStore]:
    url = database_url(settings)
    upgrade_database(url)
    engine = _engine(url)
    _restrict_sqlite_file(url)
    return ConversationStore(engine), DeploymentAccessStore(engine)


def open_store_at(url: str) -> ConversationStore:
    """Open a store at an explicit URL. Used by tests and by open_store."""
    return open_stores_at(url)[0]


def open_stores_at(url: str) -> tuple[ConversationStore, DeploymentAccessStore]:
    upgrade_database(url)
    engine = _engine(url)
    return ConversationStore(engine), DeploymentAccessStore(engine)


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
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def _restrict_sqlite_file(url: str) -> None:
    made = make_url(url)
    if not made.drivername.startswith("sqlite") or not made.database:
        return
    if made.database == ":memory:":
        return
    path = Path(made.database)
    if path.exists():
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
