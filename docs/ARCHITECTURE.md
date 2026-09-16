# Architecture

Browser -> FastAPI -> SQLite/local media -> local AI -> official social APIs.

Local AI components:
- Ollama: title/description/hashtags/keywords
- faster-whisper: speech-to-text
- Argos Translate: translation
- Piper: text-to-speech
- FFmpeg: media processing

The scheduler checks the queue every 30 seconds while the application is running. This is a private self-hosted tool, not a SaaS service.
