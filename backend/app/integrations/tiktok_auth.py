"""TikTok Login Kit OAuth code exchange and rotating refresh-token persistence."""
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from filelock import FileLock
from ..config import settings

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def save_private(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
            json.dump(data, output)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _exchange(values: dict) -> dict:
    if not settings.tiktok_client_key or not settings.tiktok_client_secret:
        raise RuntimeError("Configure TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET for OAuth/refresh")
    try:
        response = httpx.post(TOKEN_URL, data={"client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret, **values}, timeout=60)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("TikTok OAuth exchange failed. Check app credentials, authorization and redirect URI.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("access_token"), str) or not data.get("refresh_token"):
        raise RuntimeError("TikTok did not grant usable tokens. Authorize the required scopes again.")
    if "video.publish" not in data.get("scope", "").split(","):
        raise RuntimeError("TikTok authorization is missing the video.publish scope")
    data["expires_at"] = time.time() + int(data.get("expires_in", 0))
    return data


def access_token() -> str:
    path = Path(settings.tiktok_token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=65):
        if path.is_file():
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                raise RuntimeError("TikTok token file is unreadable; authorize the account again") from exc
            if not isinstance(data, dict):
                raise RuntimeError("Invalid TikTok token file")
            if float(data.get("expires_at", 0)) <= time.time() + 120:
                if not data.get("refresh_token"):
                    raise RuntimeError("TikTok refresh token is missing; authorize again")
                data = _exchange({"grant_type": "refresh_token", "refresh_token": data["refresh_token"]})
                save_private(path, data)
            if not data.get("access_token"):
                raise RuntimeError("TikTok access token is missing; authorize again")
            return data["access_token"]
    if settings.tiktok_access_token:
        return settings.tiktok_access_token
    raise RuntimeError("TikTok authorization required. Connect the selected account or configure its token.")


def authorization_url(account_key: str) -> str:
    parsed = urlsplit(settings.tiktok_redirect_uri)
    if parsed.scheme != "https" or not parsed.netloc or parsed.fragment or parsed.query:
        raise ValueError("Configure an HTTPS TIKTOK_REDIRECT_URI ending in /api/tiktok/oauth/callback and register it with TikTok")
    if parsed.path != "/api/tiktok/oauth/callback" or not settings.tiktok_client_key:
        raise ValueError("TikTok client key and exact callback URI must be configured")
    state = secrets.token_urlsafe(32)
    root = Path(settings.accounts_dir).parent / "oauth-state"
    save_private(root / f"{state}.json", {"account_key": account_key, "expires_at": time.time() + 600})
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": settings.tiktok_client_key, "response_type": "code",
        "scope": "user.info.basic,video.publish", "redirect_uri": settings.tiktok_redirect_uri, "state": state})


def consume_state(state: str) -> str:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,60}", state):
        raise ValueError("Invalid OAuth state")
    path = Path(settings.accounts_dir).parent / "oauth-state" / f"{state}.json"
    with FileLock(str(path) + ".lock", timeout=5):
        if not path.is_file():
            raise ValueError("OAuth state has expired or was already used")
        data = json.loads(path.read_text())
        path.unlink()
    if data["expires_at"] < time.time():
        raise ValueError("OAuth state expired; connect again")
    return data["account_key"]


def complete_authorization(code: str):
    if not code:
        raise ValueError("TikTok authorization code missing")
    data = _exchange({"grant_type": "authorization_code", "code": code, "redirect_uri": settings.tiktok_redirect_uri})
    path = Path(settings.tiktok_token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=65):
        save_private(path, data)
