from datetime import datetime
from typing import Literal

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
    account_key: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    facebook_mode: Literal["reel", "post"] = "reel"
    youtube_privacy: Literal["private", "public", "unlisted"] = "private"
    disable_comment: bool = True
    disable_duet: bool = True
    disable_stitch: bool = True
    brand_content_toggle: bool = False
    brand_organic_toggle: bool = False
    is_aigc: bool = False
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
    speaker_id: int | None = Field(default=None, ge=0)


class CaptionItem(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str


class CaptionSaveRequest(BaseModel):
    captions: list[CaptionItem]


class RenderRequest(BaseModel):
    narration_policy: Literal["extend", "trim"] = "extend"
    image_duration: int = Field(default=10, ge=1, le=300)
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


class TaskRequest(BaseModel):
    content_id: int = Field(gt=0)
    action: Literal["generate", "metadata", "translate", "voice", "voice-captions", "render"]
    options: dict = Field(default_factory=dict)
