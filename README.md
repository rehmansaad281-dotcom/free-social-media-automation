# Free Social Media Automation

Private/self-hosted automation tool for the owner's Facebook Pages, YouTube channel(s), and TikTok account(s).

## Included
- Local media library and upload limit
- Local Ollama AI: title, description, hashtags, keywords
- faster-whisper speech-to-text with word timestamps
- Editable word-level caption records
- Argos Translate for local translation
- Piper local TTS with selectable local voice models
- FFmpeg voice-over replacement and optional burned subtitles
- Scheduling queue, retries, history, delete/retry controls
- Facebook Page posts and video/Reel adapter
- YouTube OAuth upload + scheduled publication support
- TikTok Direct Post upload + creator-info validation + status polling
- SQLite persistence
- No subscriptions, billing, paid AI API, browser automation, or restriction bypass

## Important platform requirements
The software is free/self-hosted, but the social platforms still require their official developer apps, permissions, OAuth/access tokens, quotas and, where applicable, review/audit. TikTok currently restricts unaudited Direct Post clients to private viewing; public posting requires the relevant approval/audit. See the official platform documentation before enabling public publishing.

## Run
Python 3.11+, FFmpeg, Ollama, faster-whisper dependencies, Argos Translate, Piper and the required platform developer credentials.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

Never commit `.env`, OAuth secrets, access tokens, model binaries, or private media.
