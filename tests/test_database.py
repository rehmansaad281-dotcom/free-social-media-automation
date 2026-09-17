from sqlalchemy import create_engine, inspect, text
from backend.app import db


def test_additive_legacy_migration_preserves_rows(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE content (id INTEGER PRIMARY KEY, title TEXT)"))
        connection.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, content_id INTEGER)"))
        connection.execute(text("INSERT INTO content VALUES (42, 'keep me')"))
        connection.execute(text("INSERT INTO jobs VALUES (7, 42)"))
    monkeypatch.setattr(db, "engine", engine)
    db._migrate_sqlite(); db._migrate_sqlite()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT title FROM content WHERE id=42")).scalar() == "keep me"
        assert connection.execute(text("SELECT content_id FROM jobs WHERE id=7")).scalar() == 42
    assert {"retry_at", "privacy_level"} <= {column["name"] for column in inspect(engine).get_columns("jobs")}
    assert "caption_audio_path" in {column["name"] for column in inspect(engine).get_columns("content")}
    engine.dispose()
