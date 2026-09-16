from datetime import datetime, timezone
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

from ..config import settings


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload"
]


def _utc_rfc3339(value: datetime) -> str:
    """
    Convert a datetime to UTC RFC3339 format required by YouTube.
    Database datetimes are stored as naive UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return (
        value
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_service():
    token = Path(settings.youtube_token_file)

    creds = (
        Credentials.from_authorized_user_file(
            str(token),
            SCOPES,
        )
        if token.exists()
        else None
    )

    if not creds or not creds.valid:
        if (
            creds
            and creds.expired
            and creds.refresh_token
        ):
            from google.auth.transport.requests import Request

            creds.refresh(Request())

        else:
            client_secret = Path(
                settings.youtube_client_secrets_file
            )

            if not client_secret.is_file():
                raise RuntimeError(
                    "YouTube client secret file not found: "
                    f"{client_secret}"
                )

            flow = (
                InstalledAppFlow.from_client_secrets_file(
                    str(client_secret),
                    SCOPES,
                )
            )

            creds = flow.run_local_server(
                port=0
            )

        token.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        token.write_text(
            creds.to_json(),
            encoding="utf-8",
        )

    return build(
        "youtube",
        "v3",
        credentials=creds,
    )


def publish_video(
    media_path: str,
    title: str,
    description: str,
    hashtags: str,
    publish_at: datetime | None = None,
    privacy: str | None = None,
) -> str:
    path = Path(media_path)

    if not path.is_file():
        raise RuntimeError(
            f"YouTube media file not found: {path}"
        )

    if path.suffix.lower() not in {
        ".mp4",
        ".mov",
        ".m4v",
        ".avi",
        ".webm",
    }:
        raise RuntimeError(
            "YouTube publishing requires a video file"
        )

    youtube = get_service()

    tags = [
        item.strip("# ")
        for item in hashtags.replace(",", " ").split()
        if item.strip("# ")
    ]

    status: dict[str, str] = {
        "privacyStatus": (
            privacy
            or settings.youtube_default_privacy
        )
    }

    if publish_at is not None:
        status["privacyStatus"] = "private"
        status["publishAt"] = _utc_rfc3339(
            publish_at
        )

    body = {
        "snippet": {
            "title": title[:100],
            "description": (
                f"{description}\n\n{hashtags}"
            )[:5000],
            "tags": tags,
            "categoryId": "22",
        },
        "status": status,
    }

    response = (
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
        .execute()
    )

    video_id = response.get("id")

    if not video_id:
        raise RuntimeError(
            "YouTube upload completed without "
            "returning a video ID"
        )

    return video_id
