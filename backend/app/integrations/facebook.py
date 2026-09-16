import httpx
from ..config import settings

class FacebookPublisher:
    def __init__(self):
        if not settings.facebook_page_id or not settings.facebook_page_access_token:
            raise RuntimeError("Facebook Page ID/access token not configured")
        self.base = f"https://graph.facebook.com/{settings.facebook_graph_version}"
        self.params = {"access_token": settings.facebook_page_access_token}

    def publish_post(self, media_path: str, description: str, hashtags: str) -> str:
        caption = "\n\n".join(x for x in [description, hashtags] if x)
        endpoint = "photos" if media_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else "videos"
        field = "caption" if endpoint == "photos" else "description"
        with open(media_path, "rb") as f:
            r = httpx.post(f"{self.base}/{settings.facebook_page_id}/{endpoint}", data={field: caption, **self.params}, files={"source": f}, timeout=900)
        r.raise_for_status()
        data = r.json()
        return str(data.get("id") or data.get("post_id") or "")

    def publish_reel(self, media_path: str, description: str, hashtags: str) -> str:
        # Page Reels use the Graph video_reels upload flow. The endpoint/version and Page permissions
        # must match the Meta app configuration used by the owner.
        caption = "\n\n".join(x for x in [description, hashtags] if x)
        with open(media_path, "rb") as f:
            init = httpx.post(f"{self.base}/{settings.facebook_page_id}/video_reels", params={**self.params, "upload_phase": "start"}, timeout=60)
        init.raise_for_status()
        data = init.json()
        video_id = data.get("video_id")
        if not video_id:
            raise RuntimeError(f"Facebook Reel init failed: {data}")
        size = __import__("os").path.getsize(media_path)
        with open(media_path, "rb") as f:
            upload = httpx.post(f"{self.base}/{settings.facebook_page_id}/video_reels", params={**self.params, "upload_phase": "transfer", "video_id": video_id, "start_offset": 0, "end_offset": size}, content=f.read(), headers={"Content-Type": "application/octet-stream"}, timeout=900)
        upload.raise_for_status()
        finish = httpx.post(f"{self.base}/{settings.facebook_page_id}/video_reels", params={**self.params, "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED", "description": caption}, timeout=300)
        finish.raise_for_status()
        return str(video_id)
