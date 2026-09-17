from datetime import datetime, timezone
from pathlib import Path
from filelock import FileLock

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

from ..config import settings


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
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

    token.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(token) + ".lock", timeout=65):
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
        from .tiktok_auth import save_private
        import json
        save_private(token, json.loads(credentials.to_json()))

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


def metadata_tags(hashtags: str, keywords: str) -> list[str]:
    values = _build_tags(hashtags) + [value.strip() for value in keywords.split(",")]
    result, length = [], 0
    for value in values:
        if not value or value in result:
            continue
        cost = len(value) + (2 if " " in value else 0) + (1 if result else 0)
        if length + cost > 500:
            raise ValueError("YouTube tags exceed the 500-character API limit")
        result.append(value)
        length += cost
    return result


def get_status(video_id: str) -> dict:
    response = get_service().videos().list(part="status,processingDetails", id=video_id).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("YouTube video not found for this authorized account")
    return items[0]


def publish_video(
    media_path: str,
    title: str,
    description: str,
    hashtags: str,
    publish_at: datetime | None = None,
    privacy: str | None = None,
    keywords: str = "",
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

    if publish_at is not None and (publish_at.replace(tzinfo=timezone.utc) if publish_at.tzinfo is None else publish_at.astimezone(timezone.utc)) > datetime.now(timezone.utc):
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
            "tags": metadata_tags(hashtags, keywords),
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
                    chunksize=8 * 1024 * 1024,
                    resumable=True,
                ),
            )
        )

        response = None
        while response is None:
            _, response = request.next_chunk(num_retries=0)

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
    import argparse
    from ..accounts import account_context
    parser = argparse.ArgumentParser(description="Authorize a configured YouTube account")
    parser.add_argument("--account-key", default="default")
    args = parser.parse_args()
    with account_context("youtube", args.account_key):
        authorize()
