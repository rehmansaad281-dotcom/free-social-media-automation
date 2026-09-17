from pathlib import Path

from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings


url = make_url(settings.database_url)
if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
    Path(url.database).parent.mkdir(parents=True, exist_ok=True)
Path(settings.media_dir).mkdir(parents=True, exist_ok=True)

connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


def _migrate_sqlite():
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)

    if "jobs" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("jobs")
    }

    if "retry_at" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE jobs "
                    "ADD COLUMN retry_at DATETIME"
                )
            )

    # Additive migrations preserve all owner records. Existing SQLite tables
    # cannot gain foreign keys without rebuilding; use scripts.audit_db first.
    with engine.begin() as connection:
        for table, column, definition in [
            ("content", "caption_audio_path", "VARCHAR(1000) NOT NULL DEFAULT ''"),
            ("jobs", "account_key", "VARCHAR(80) NOT NULL DEFAULT 'default'"),
            ("jobs", "options_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("jobs", "privacy_level", "VARCHAR(50) NOT NULL DEFAULT ''"),
        ]:
            existing = {item["name"] for item in inspect(connection).get_columns(table)}
            if column not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def init_db():
    from . import models

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
    _install_sqlite_guards()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def _install_sqlite_guards():
    """Add non-destructive integrity enforcement to legacy SQLite tables too.

    Existing invalid rows remain auditable; inserts/updates cannot add new orphans.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        for child, column, parent in [
            ("content", "media_id", "media"), ("captions", "content_id", "content"),
            ("jobs", "content_id", "content"), ("media_tasks", "content_id", "content"),
            ("publication_attempts", "job_id", "jobs"),
        ]:
            for operation in ("INSERT", "UPDATE"):
                connection.execute(text(f"""CREATE TRIGGER IF NOT EXISTS guard_{child}_{column}_{operation.lower()}
                    BEFORE {operation} ON {child}
                    WHEN NEW.{column} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {parent} WHERE id=NEW.{column})
                    BEGIN SELECT RAISE(ABORT, 'Referenced record does not exist'); END"""))
            connection.execute(text(f"""CREATE TRIGGER IF NOT EXISTS guard_{parent}_{child}_delete
                BEFORE DELETE ON {parent} WHEN EXISTS (SELECT 1 FROM {child} WHERE {column}=OLD.id)
                BEGIN SELECT RAISE(ABORT, 'Referenced records cannot be deleted'); END"""))
        for operation in ("INSERT", "UPDATE"):
            connection.execute(text(f"""CREATE TRIGGER IF NOT EXISTS guard_caption_timing_{operation.lower()}
                BEFORE {operation} ON captions WHEN NEW.start_ms<0 OR NEW.end_ms<=NEW.start_ms OR trim(NEW.text)=''
                BEGIN SELECT RAISE(ABORT, 'Invalid caption timing or text'); END"""))
