from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Media(Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(500))
    path: Mapped[str] = mapped_column(String(1000))
    media_type: Mapped[str] = mapped_column(String(30))
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class Content(Base):
    __tablename__ = "content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("media.id", ondelete="RESTRICT"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[str] = mapped_column(Text, default="")
    transcript: Mapped[str] = mapped_column(Text, default="")
    translated_text: Mapped[str] = mapped_column(Text, default="")
    source_language: Mapped[str] = mapped_column(
        String(20),
        default="",
    )
    target_language: Mapped[str] = mapped_column(
        String(20),
        default="en",
    )
    voice_id: Mapped[str] = mapped_column(
        String(200),
        default="",
    )
    voice_path: Mapped[str] = mapped_column(
        String(1000),
        default="",
    )
    caption_audio_path: Mapped[str] = mapped_column(String(1000), default="")
    rendered_media_path: Mapped[str] = mapped_column(
        String(1000),
        default="",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="DRAFT",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Caption(Base):
    __tablename__ = "captions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("content.id", ondelete="RESTRICT"),
        index=True,
    )
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voice_id: Mapped[str] = mapped_column(
        String(200),
        unique=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    gender: Mapped[str] = mapped_column(
        String(30),
        default="neutral",
    )
    language: Mapped[str] = mapped_column(
        String(30),
        default="en",
    )
    model_path: Mapped[str] = mapped_column(
        String(1000),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("content.id", ondelete="RESTRICT"),
        index=True,
    )
    platform: Mapped[str] = mapped_column(
        String(30),
    )

    account_key: Mapped[str] = mapped_column(String(80), default="default")
    options_json: Mapped[str] = mapped_column(Text, default="{}")
    privacy_level: Mapped[str] = mapped_column(String(50), default="")

    # Original user-requested publication time.
    publish_at: Mapped[datetime] = mapped_column(
        DateTime,
        index=True,
    )

    # Temporary retry time. This must never overwrite
    # the original publish_at.
    retry_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="QUEUED",
    )
    external_id: Mapped[str] = mapped_column(
        String(500),
        default="",
    )
    error: Mapped[str] = mapped_column(
        Text,
        default="",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    platform: Mapped[str] = mapped_column(
        String(30),
        index=True,
    )
    account_name: Mapped[str] = mapped_column(
        String(200),
    )
    account_id: Mapped[str] = mapped_column(
        String(300),
        default="",
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class PublicationAttempt(Base):
    """Durable attempt journal; remote outcomes may require owner reconciliation."""
    __tablename__ = "publication_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="PUBLISHING")
    external_id: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MediaTask(Base):
    __tablename__ = "media_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("content.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    result: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
