import os
from urllib.parse import urlsplit
from pathlib import Path

import httpx

from ..config import settings
from ..media import probe
from .tiktok_auth import access_token


BASE = "https://open.tiktokapis.com/v2"

SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer "
            f"{access_token()}"
        ),
        "Content-Type": "application/json",
    }


def _json_response(
    response: httpx.Response,
    action: str,
) -> dict:
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            f"TikTok {action} returned invalid JSON"
        )

    if not isinstance(data, dict):
        raise RuntimeError(f"TikTok {action} returned an invalid response")

    error = data.get("error") or {}
    if not response.is_success or not isinstance(error, dict) or error.get("code") not in {None, "ok"}:
        raise RuntimeError(f"TikTok {action} failed (HTTP {response.status_code}). Check authorization, creator eligibility and platform limits.")
    return data


def creator_info() -> dict:
    response = httpx.post(
        f"{BASE}/post/publish/"
        f"creator_info/query/",
        headers=_headers(),
        timeout=60,
    )

    data = _json_response(
        response,
        "creator info request",
    )

    return data.get(
        "data",
        {},
    )


def _select_privacy(
    info: dict,
    requested: str | None,
) -> str:
    allowed = info.get(
        "privacy_level_options"
    ) or []

    privacy = (
        requested
        or settings.tiktok_privacy_level
    )

    if not allowed or privacy not in allowed:
        raise RuntimeError(
            "Configured TikTok privacy level "
            f"'{privacy}' is not allowed. "
            f"Available options: {allowed}"
        )

    return privacy


def publish_video(
    media_path: str,
    title: str,
    privacy_level: str | None = None,
    options: dict | None = None,
) -> str:
    path = Path(
        media_path
    )

    if not path.is_file():
        raise RuntimeError(
            f"TikTok media file not found: {path}"
        )

    extension = path.suffix.lower()

    content_type = (
        SUPPORTED_VIDEO_EXTENSIONS.get(
            extension
        )
    )

    if not content_type:
        raise RuntimeError(
            "TikTok publishing requires "
            "MP4, MOV, or WebM video"
        )

    info = creator_info()

    privacy = _select_privacy(
        info,
        privacy_level,
    )

    options = options or {}
    media_info = probe(str(path))
    duration = float(media_info.get("format", {}).get("duration", 0))
    maximum = info.get("max_video_post_duration_sec")
    if not isinstance(maximum, (int, float)) or maximum <= 0:
        raise RuntimeError("TikTok creator information did not include a valid maximum video duration")
    if duration <= 0 or duration > maximum:
        raise ValueError("Video exceeds this TikTok creator's duration limit or has no valid duration")
    if options.get("brand_content_toggle") and privacy == "SELF_ONLY":
        raise ValueError("TikTok branded content cannot use private visibility")

    file_size = os.path.getsize(
        path
    )

    if file_size <= 0:
        raise ValueError("TikTok video is empty")
    # The last chunk absorbs the remainder (rather than a too-small extra chunk).
    chunk_size = min(file_size, 10_000_000)
    total_chunks = max(1, file_size // chunk_size)
    if total_chunks > 1000:
        raise ValueError("TikTok video exceeds the supported chunk limit")

    payload = {
        "post_info": {
            "title": title[:2200],
            "privacy_level": privacy,
            "disable_duet": bool(
                info.get(
                    "duet_disabled",
                    False,
                )
            ),
            "disable_comment": bool(
                info.get(
                    "comment_disabled",
                    False,
                )
            ),
            "disable_stitch": bool(
                info.get(
                    "stitch_disabled",
                    False,
                )
            ),
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        },
    }

    for field in ("disable_comment", "disable_duet", "disable_stitch"):
        payload["post_info"][field] = payload["post_info"][field] or options.get(field, True)
    for field in ("brand_content_toggle", "brand_organic_toggle", "is_aigc"):
        payload["post_info"][field] = bool(options.get(field, False))

    response = httpx.post(
        f"{BASE}/post/publish/"
        f"video/init/",
        headers=_headers(),
        json=payload,
        timeout=60,
    )

    data = _json_response(
        response,
        "video initialization",
    )

    result = data.get(
        "data",
        {},
    )

    upload_url = result.get(
        "upload_url"
    )

    publish_id = result.get(
        "publish_id"
    )

    if not upload_url or not publish_id:
        raise RuntimeError(
            "TikTok initialization did not "
            "return upload_url and publish_id"
        )

    parsed = urlsplit(upload_url)
    if parsed.scheme != "https" or not parsed.hostname or not (
        parsed.hostname.endswith(".tiktokapis.com") or parsed.hostname.endswith(".tiktok.com")
    ) or parsed.username:
        raise RuntimeError("TikTok returned an untrusted upload URL")

    with path.open("rb") as media:
        offset = 0

        while offset < file_size:
            remaining = file_size - offset
            chunk = media.read(remaining if remaining < 2 * chunk_size else chunk_size)

            if not chunk:
                break

            end = (
                offset
                + len(chunk)
                - 1
            )

            upload_response = httpx.put(
                upload_url,
                headers={
                    "Content-Type":
                        content_type,
                    "Content-Length":
                        str(len(chunk)),
                    "Content-Range": (
                        f"bytes "
                        f"{offset}-{end}/"
                        f"{file_size}"
                    ),
                },
                content=chunk,
                timeout=900,
            )

            if not upload_response.is_success:
                raise RuntimeError(
                    "TikTok binary upload failed. Inspect the saved publish ID before retrying."
                )

            offset = end + 1

    if offset != file_size:
        raise RuntimeError(
            "TikTok upload ended before "
            "the complete file was transferred"
        )

    return str(
        publish_id
    )


def get_status(
    publish_id: str,
) -> dict:
    if not publish_id:
        raise ValueError(
            "TikTok publish ID is required"
        )

    response = httpx.post(
        f"{BASE}/post/publish/"
        f"status/fetch/",
        headers=_headers(),
        json={
            "publish_id": publish_id,
        },
        timeout=60,
    )

    data = _json_response(
        response,
        "publish status request",
    )

    return data.get(
        "data",
        {},
    )
