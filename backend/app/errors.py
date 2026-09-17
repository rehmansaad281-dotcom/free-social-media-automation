"""Safe public diagnostics; never return subprocess output or credential-bearing URLs."""
import re
from .config import settings


def public_error(error: Exception | str) -> str:
    message = str(error)
    for secret in (settings.facebook_page_access_token, settings.tiktok_access_token):
        if secret:
            message = message.replace(secret, "[redacted]")
    message = re.sub(r'https?://[^\s]+', '[service URL]', message)
    message = re.sub(r'(?:[A-Za-z]:)?/[^\s,;]+', '[path]', message)
    return message[:500]
