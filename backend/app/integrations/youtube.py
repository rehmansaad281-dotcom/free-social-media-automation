from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from ..config import settings

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_service():
    token = Path(settings.youtube_token_file)
    creds = Credentials.from_authorized_user_file(token, SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(settings.youtube_client_secrets_file, SCOPES)
            creds = flow.run_local_server(port=0)
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)

def publish_video(media_path: str, title: str, description: str, hashtags: str, publish_at=None, privacy: str | None = None) -> str:
    youtube = get_service()
    tags = [x.strip("# ") for x in hashtags.replace(",", " ").split() if x.strip("# ")]
    status = {"privacyStatus": privacy or ("private" if publish_at else settings.youtube_default_privacy)}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.isoformat().replace("+00:00", "Z")
    body = {"snippet": {"title": title[:100], "description": f"{description}\n\n{hashtags}"[:5000], "tags": tags, "categoryId": "22"}, "status": status}
    response = youtube.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(media_path, chunksize=-1, resumable=True)).execute()
    return response["id"]
