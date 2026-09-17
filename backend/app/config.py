from pydantic import Field
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Free Social Automation"

    database_url: str = "sqlite:///./data/app.db"

    media_dir: str = "./media"

    host: str = "0.0.0.0"
    port: int = 8000

    max_upload_mb: int = Field(default=2048, ge=1, le=10240)

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"

    whisper_binary: str = "./whisper.cpp/build/bin/whisper-cli"
    whisper_model: str = "./models/whisper/ggml-base.bin"

    piper_bin: str = "piper"
    piper_model: str = "./models/piper/voice.onnx"
    piper_voice_dir: str = "./models/piper"

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    process_timeout: int = Field(default=1800, ge=1, le=86400)
    scheduler_enabled: bool = True
    auth_username: str = "owner"
    auth_password: str = ""
    translation_backend: Literal["ollama", "argos"] = "ollama"

    facebook_graph_version: str = "v23.0"
    facebook_page_id: str = ""
    facebook_page_access_token: str = ""

    youtube_client_secrets_file: str = (
        "./secrets/youtube_client_secret.json"
    )
    youtube_token_file: str = "./secrets/youtube_token.json"
    youtube_default_privacy: Literal["private", "public", "unlisted"] = "private"

    tiktok_access_token: str = ""
    tiktok_privacy_level: str = "SELF_ONLY"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
