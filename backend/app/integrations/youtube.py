from datetime import datetime, timezone
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

from ..config import settings


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]


SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".webm",
}


def _utc_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )
    else:
        value = value.astimezone(
            timezone.utc
        )

    return (
        value
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_service():
    token = Path(
        settings.youtube_token_file
    )

    credentials = None

    if token.is_file():
        credentials = (
            Credentials.from_authorized_user_file(
                str(token),
                SCOPES,
            )
        )

    if (
        credentials
        and credentials.expired
        and credentials.refresh_token
    ):
        from google.auth.transport.requests import (
            Request,
        )

        credentials.refresh(
            Request()
        )

    if not credentials or not credentials.valid:
        raise RuntimeError("YouTube authorization required. Run python -m backend.app.integrations.youtube on the owner's local machine first.")
    token.parent.mkdir(parents=True, exist_ok=True)
    temporary = token.with_suffix(".tmp")
    temporary.touch(mode=0o600, exist_ok=True)
    temporary.chmod(0o600)
    temporary.write_text(credentials.to_json(), encoding="utf-8")
    temporary.replace(token)

    return build(
        "youtube",
        "v3",
        credentials=credentials,
    )


def _build_tags(
    hashtags: str,
) -> list[str]:
    values = (
        hashtags
        .replace(",", " ")
        .split()
    )

    tags = []

    for value in values:
        tag = value.strip("# ")

        if tag:
            tags.append(tag)

    return tags


def publish_video(
    media_path: str,
    title: str,
    description: str,
    hashtags: str,
    publish_at: datetime | None = None,
    privacy: str | None = None,
) -> str:
    path = Path(
        media_path
    )

    if not path.is_file():
        raise RuntimeError(
            f"YouTube media file not found: {path}"
        )

    if path.suffix.lower() not in (
        SUPPORTED_VIDEO_EXTENSIONS
    ):
        raise RuntimeError(
            "YouTube publishing requires "
            "a supported video file"
        )

    if not title.strip():
        raise ValueError("YouTube title is required")
    if (privacy or settings.youtube_default_privacy) not in {"private", "public", "unlisted"}:
        raise ValueError("Invalid YouTube privacy setting")
    youtube = get_service()

    status: dict[str, str] = {
        "privacyStatus": (
            privacy
            or settings.youtube_default_privacy
        ),
    }

    if publish_at is not None:
        status = {
            "privacyStatus": "private",
            "publishAt": _utc_rfc3339(
                publish_at
            ),
        }

    body = {
        "snippet": {
            "title": title.strip()[:100],
            "description": (
                f"{description}\n\n{hashtags}"
            ).strip()[:5000],
            "tags": _build_tags(
                hashtags
            ),
            "categoryId": "22",
        },
        "status": status,
    }

    try:
        request = (
            youtube.videos()
            .insert(
                part="snippet,status",
                body=body,
                media_body=MediaFileUpload(
                    str(path),
                    chunksize=-1,
                    resumable=True,
                ),
            )
        )

        response = request.execute()

    except Exception as exc:
        raise RuntimeError(
            "YouTube upload failed. Check authorization, quota, video metadata, and the platform upload history before retrying."
        ) from exc

    video_id = response.get("id")

    if not video_id:
        raise RuntimeError(
            "YouTube upload completed without "
            "returning a video ID"
        )

    return str(video_id)


def authorize():
    """Explicit interactive setup only; never run OAuth in the queue worker."""
    flow = InstalledAppFlow.from_client_secrets_file(settings.youtube_client_secrets_file, SCOPES)
    credentials = flow.run_local_server(port=0)
    token = Path(settings.youtube_token_file)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.touch(mode=0o600, exist_ok=True)
    token.chmod(0o600)
    token.write_text(credentials.to_json(), encoding="utf-8")


if __name__ == "__main__":
    authorize()
