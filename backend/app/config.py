from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Free Social Automation"

    database_url: str = "sqlite:///./data/app.db"

    media_dir: str = "./media"

    host: str = "0.0.0.0"
    port: int = 8000

    max_upload_mb: int = 2048

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"

    whisper_binary: str = "./whisper.cpp/build/bin/whisper-cli"
    whisper_model: str = "./models/whisper/ggml-base.bin"

    piper_bin: str = "piper"
    piper_model: str = "./models/piper/voice.onnx"
    piper_voice_dir: str = "./models/piper"

    ffmpeg_bin: str = "ffmpeg"

    facebook_graph_version: str = "v23.0"
    facebook_page_id: str = ""
    facebook_page_access_token: str = ""

    youtube_client_secrets_file: str = (
        "./secrets/youtube_client_secret.json"
    )
    youtube_token_file: str = "./secrets/youtube_token.json"
    youtube_default_privacy: str = "private"

    tiktok_access_token: str = ""
    tiktok_privacy_level: str = "SELF_ONLY"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
