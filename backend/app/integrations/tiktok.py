import os
import httpx
from ..config import settings

BASE = "https://open.tiktokapis.com/v2"

def creator_info():
    r = httpx.post(f"{BASE}/post/publish/creator_info/query/", headers={"Authorization": f"Bearer {settings.tiktok_access_token}", "Content-Type": "application/json"}, timeout=60)
    r.raise_for_status(); return r.json().get("data", {})

def publish_video(media_path: str, title: str, privacy_level: str | None = None) -> str:
    if not settings.tiktok_access_token:
        raise RuntimeError("TikTok access token not configured")
    info = creator_info()
    allowed = info.get("privacy_level_options") or [settings.tiktok_privacy_level]
    privacy = privacy_level or settings.tiktok_privacy_level
    if privacy not in allowed:
        privacy = allowed[0]
    size = os.path.getsize(media_path)
    chunk = min(size, 10_000_000)
    total = (size + chunk - 1) // chunk
    payload = {"post_info": {"title": title[:2200], "privacy_level": privacy, "disable_duet": bool(info.get("duet_disabled", False)), "disable_comment": bool(info.get("comment_disabled", False)), "disable_stitch": bool(info.get("stitch_disabled", False))}, "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}}
    r = httpx.post(f"{BASE}/post/publish/video/init/", headers={"Authorization": f"Bearer {settings.tiktok_access_token}", "Content-Type": "application/json"}, json=payload, timeout=60)
    r.raise_for_status(); data = r.json().get("data", {})
    upload_url, publish_id = data.get("upload_url"), data.get("publish_id")
    if not upload_url or not publish_id: raise RuntimeError(f"TikTok init failed: {r.text}")
    with open(media_path, "rb") as f:
        offset = 0
        while offset < size:
            body = f.read(chunk)
            end = offset + len(body) - 1
            rr = httpx.put(upload_url, headers={"Content-Type": "video/mp4", "Content-Length": str(len(body)), "Content-Range": f"bytes {offset}-{end}/{size}"}, content=body, timeout=900)
            rr.raise_for_status()
            offset = end + 1
    return publish_id

def get_status(publish_id: str) -> dict:
    r = httpx.post(f"{BASE}/post/publish/status/fetch/", headers={"Authorization": f"Bearer {settings.tiktok_access_token}", "Content-Type": "application/json"}, json={"publish_id": publish_id}, timeout=60)
    r.raise_for_status(); return r.json().get("data", {})
