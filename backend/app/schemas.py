from datetime import datetime

from pydantic import BaseModel, Field


class ContentCreate(BaseModel):
    media_id: int | None = None
    title: str = ""
    description: str = ""
    hashtags: str = ""
    keywords: str = ""
    target_language: str = "en"


class ContentUpdate(BaseModel):
    media_id: int | None = None
    title: str | None = None
    description: str | None = None
    hashtags: str | None = None
    keywords: str | None = None
    target_language: str | None = None


class ScheduleCreate(BaseModel):
    content_id: int
    platform: str
    privacy_level: str | None = None
    consent: bool = False
    publish_at: datetime
    max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
    )


class VoiceRequest(BaseModel):
    content_id: int
    text: str
    voice_id: str | None = None


class CaptionItem(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str


class CaptionSaveRequest(BaseModel):
    captions: list[CaptionItem]


class RenderRequest(BaseModel):
    content_id: int
    use_voiceover: bool = True
    burn_subtitles: bool = False
    subtitle_font_size: int = Field(
        default=48,
        ge=12,
        le=120,
    )


class ReconcileRequest(BaseModel):
    published: bool
    external_id: str = Field(default="", max_length=500)
    note: str = Field(min_length=10, max_length=1000)
