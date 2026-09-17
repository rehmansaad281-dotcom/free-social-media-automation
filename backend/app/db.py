from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings


Path("data").mkdir(exist_ok=True)
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


def init_db():
    from . import models

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
