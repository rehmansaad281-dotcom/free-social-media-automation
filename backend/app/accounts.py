"""Server-side credential profiles. Only public labels reach the browser."""
import json
import re
from contextlib import contextmanager
from pathlib import Path
from .config import settings, account_overrides

FIELDS = {
    "facebook": {"facebook_page_id", "facebook_page_access_token"},
    "youtube": {"youtube_client_secrets_file", "youtube_token_file", "youtube_default_privacy"},
    "tiktok": {"tiktok_access_token", "tiktok_token_file", "tiktok_client_key", "tiktok_client_secret", "tiktok_redirect_uri"},
}


def profile(platform: str, key: str = "default") -> dict:
    if platform not in FIELDS:
        raise ValueError("Unsupported account platform")
    if key == "default":
        return {"name": "Configured default", "settings": {}}
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key):
        raise ValueError("Invalid account key")
    root = Path(settings.accounts_dir).resolve()
    path = (root / f"{platform}-{key}.json").resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Account profile not found; configure its server-side JSON file")
    try:
        data = json.loads(path.read_text())
        values = data["settings"]
        if not isinstance(values, dict) or not set(values) <= FIELDS[platform] or not all(isinstance(v, str) for v in values.values()):
            raise ValueError()
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError()
        # Do not accidentally inherit another account's credentials.
        required = {"facebook": {"facebook_page_id", "facebook_page_access_token"},
                    "youtube": {"youtube_token_file", "youtube_client_secrets_file"},
                    "tiktok": {"tiktok_token_file"}}[platform]
        if not all(values.get(field) for field in required):
            raise ValueError()
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Invalid account profile. Check required credential fields and its display name.") from exc


@contextmanager
def account_context(platform: str, key: str = "default"):
    data = profile(platform, key)
    values = data["settings"].copy()
    if key != "default" and platform == "tiktok":
        values.setdefault("tiktok_access_token", "")
    token = account_overrides.set(values)
    try:
        yield
    finally:
        account_overrides.reset(token)


def list_accounts():
    result = [{"platform": p, "key": "default", "name": "Configured default"} for p in FIELDS]
    root = Path(settings.accounts_dir)
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            platform, _, key = path.stem.partition("-")
            if platform in FIELDS:
                try:
                    data = profile(platform, key)
                    result.append({"platform": platform, "key": key, "name": data["name"]})
                except ValueError:
                    result.append({"platform": platform, "key": key, "name": "Invalid profile", "invalid": True})
    return result
