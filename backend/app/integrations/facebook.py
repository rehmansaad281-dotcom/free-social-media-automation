import httpx
from urllib.parse import urlsplit

from ..config import settings


class FacebookPublisher:
    def __init__(self):
        if not settings.facebook_page_id:
            raise RuntimeError(
                "Facebook Page ID not configured"
            )

        if not settings.facebook_page_access_token:
            raise RuntimeError(
                "Facebook Page access token not configured"
            )

        self.base = (
            f"https://graph.facebook.com/"
            f"{settings.facebook_graph_version}"
        )

        self.params = {
            "access_token": settings.facebook_page_access_token,
        }

    @staticmethod
    def _caption(
        description: str,
        hashtags: str,
    ) -> str:
        return "\n\n".join(
            value.strip()
            for value in (description, hashtags)
            if value and value.strip()
        )

    @staticmethod
    def _raise_for_response(
        response: httpx.Response,
        action: str,
    ) -> dict:
        try:
            data = response.json()
        except ValueError:
            data = {}

        if not response.is_success or not isinstance(data, dict) or data.get("error"):
            raise RuntimeError(f"Facebook {action} failed (HTTP {response.status_code}). Check token permissions, media eligibility and Page dashboard.")
        return data

    def publish_post(
        self,
        media_path: str,
        description: str,
        hashtags: str,
    ) -> str:
        caption = self._caption(
            description,
            hashtags,
        )

        lower_path = media_path.lower()

        if lower_path.endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            endpoint = "photos"
            field = "caption"
        elif lower_path.endswith(
            (".mp4", ".mov", ".m4v", ".avi", ".webm")
        ):
            endpoint = "videos"
            field = "description"
        else:
            raise RuntimeError(
                "Unsupported Facebook media format"
            )

        with open(media_path, "rb") as media:
            response = httpx.post(
                f"{self.base}/"
                f"{settings.facebook_page_id}/"
                f"{endpoint}",
                data={
                    field: caption,
                    **self.params,
                },
                files={
                    "source": media,
                },
                timeout=900,
            )

        data = self._raise_for_response(
            response,
            "post",
        )

        external_id = (
            data.get("id")
            or data.get("post_id")
        )

        if not external_id:
            raise RuntimeError(
                "Facebook post completed without "
                "returning an external ID"
            )

        return str(external_id)

    def publish_reel(
        self,
        media_path: str,
        description: str,
        hashtags: str,
    ) -> str:
        caption = self._caption(
            description,
            hashtags,
        )

        lower_path = media_path.lower()

        if not lower_path.endswith(
            (".mp4", ".mov", ".m4v", ".webm")
        ):
            raise RuntimeError(
                "Facebook Reel requires a supported "
                "video file"
            )

        init_response = httpx.post(
            f"{self.base}/"
            f"{settings.facebook_page_id}/"
            f"video_reels",
            params={
                **self.params,
                "upload_phase": "start",
            },
            timeout=60,
        )

        init_data = self._raise_for_response(
            init_response,
            "Reel initialization",
        )

        video_id = init_data.get("video_id")

        if not video_id:
            raise RuntimeError(
                "Facebook Reel initialization "
                "did not return a video ID"
            )

        import os

        file_size = os.path.getsize(
            media_path
        )

        upload_url = init_data.get("upload_url", "")
        parsed = urlsplit(upload_url)
        if parsed.scheme != "https" or parsed.hostname != "rupload.facebook.com" or parsed.username:
            raise RuntimeError("Facebook returned an invalid Reel upload URL")
        with open(media_path, "rb") as media:
            upload_response = httpx.post(
                upload_url,
                content=iter(lambda: media.read(1024 * 1024), b""),
                headers={"Authorization": f"OAuth {settings.facebook_page_access_token}",
                         "offset": "0", "file_size": str(file_size),
                         "Content-Type": "application/octet-stream", "Content-Length": str(file_size)},
                timeout=900,
            )

        self._raise_for_response(
            upload_response,
            "Reel transfer",
        )

        finish_response = httpx.post(
            f"{self.base}/"
            f"{settings.facebook_page_id}/"
            f"video_reels",
            params={
                **self.params,
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": caption,
            },
            timeout=300,
        )

        finish_data = self._raise_for_response(
            finish_response,
            "Reel publishing",
        )

        if finish_data.get("success") is not True:
            raise RuntimeError("Facebook did not confirm Reel publishing")

        external_id = (
            finish_data.get("video_id")
            or finish_data.get("id")
            or video_id
        )

        return str(external_id)


    def get_status(self, video_id: str) -> dict:
        response = httpx.get(f"{self.base}/{video_id}", params={"fields": "status", **self.params}, timeout=60)
        data = self._raise_for_response(response, "video status")
        status = data.get("status")
        if not isinstance(status, dict):
            raise RuntimeError("Facebook returned no video processing status")
        return status
