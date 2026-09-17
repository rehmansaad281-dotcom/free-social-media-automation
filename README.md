# Free Social Media Automation

Private, single-owner social automation using local media/AI and official platform APIs. No paid AI, scraping, browser publishing automation, or platform restriction bypass.

**Deployment status: NOT READY for an unqualified production sign-off.** See [audit and verification report](docs/FOLLOWUP_REPORT.md) for tested behavior and remaining limitations. Multiple Facebook Pages, YouTube channels and TikTok accounts are routed through server-side profiles. See [account setup](docs/ACCOUNTS.md).

## Workflow

1. Upload a supported image/video. Uploads require FFprobe and must have readable media streams.
2. Save a draft or load an existing Content ID. Save updates a loaded draft; **New Draft** creates a separate one.
3. Generate transcript/captions with **whisper.cpp**, then metadata with **Ollama**. These can run independently. A metadata failure does not erase a successful transcript.
4. Edit word captions in milliseconds. Blank, negative, overlapping, duplicate and zero-duration cues are rejected.
5. Translate using Ollama (default) or optional **Argos Translate**.
6. Generate speech using an installed **Piper** voice. Both `.onnx` and `.onnx.json` are required.
7. If using voice-over with captions, **Generate Captions from Voice-over** first: original audio timings do not match synthesized/translated audio.
8. Render a browser-compatible H.264/AAC MP4, preview it, and schedule. Rendering never overwrites the source. Short speech is padded. Longer narration can extend the final frame (default) or be trimmed explicitly. Still images can render to timed MP4 videos.
9. Inspect queue and attempt history. Uncertain remote outcomes require explicit owner reconciliation, not blind retries.

## Local setup

Python 3.11+, FFmpeg **and FFprobe** on PATH, plus the chosen local AI executables/models:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
# For YouTube:
pip install -r backend/requirements-youtube.txt
# Optional alternative to Ollama translation:
pip install -r backend/requirements-argos.txt
cp .env.example .env
```

Set a strong unique `AUTH_PASSWORD` in `.env`. Without it, the UI/API fail closed (health endpoints remain public). The browser prompts for HTTP Basic credentials (`AUTH_USERNAME=owner`). Never place credentials in source code or chat.

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open `http://127.0.0.1:8000`. Use **one process / one Uvicorn worker, without reload**, for the production scheduler. The app must remain running for scheduling. Dates from the UI are converted to UTC; API schedule requests must include an offset.

For remote access use an HTTPS authenticated reverse proxy or private VPN. Do not expose plain HTTP Basic authentication on the public internet. Preview environments need a `0.0.0.0` bind; browser API URLs are same-origin relative URLs.

See [AI setup](docs/SETUP_LOCAL_AI.md), [platform setup](docs/PLATFORM_NOTES.md), and [architecture](docs/ARCHITECTURE.md).

## Docker

The image installs FFmpeg/FFprobe and YouTube Python dependencies, **not AI models, whisper.cpp, Piper, Ollama, or Argos**. Install/mount Linux-compatible executables and their runtime libraries under `./bin`, configure `WHISPER_BINARY=/app/bin/whisper-cli`, `PIPER_BIN=/app/bin/piper`, and use `/app/models/...` model paths. A host-built dynamically linked binary must be compatible with the image; a mere mount is not an installation of its dependencies.

The service runs as UID/GID 10001. Precreate `data`, `media`, `secrets`, `models`, and `bin`; writable mounts (`data`, `media`, `secrets`) must be owned by UID 10001. Protect secrets with restrictive permissions. Models/bin are read-only. Set `OLLAMA_BASE_URL` to a service reachable **from the container**, not the host's loopback address. Compose binds the application port to host loopback by default.

```bash
docker compose up --build -d
```

Docker is verified by the GitHub CI image build and in-container real-media smoke-test job when that check passes; consult the follow-up report for the latest recorded result.

## Tests and data safety

```bash
pip install -r backend/requirements-test.txt
python -m compileall -q backend scripts tests
python -m pytest -q
python scripts/check_structure.py  # requires Node.js for JS syntax checking
pip check
```

Tests isolate SQLite/media in temporary directories and do not publish to real accounts. CI installs FFmpeg and runs the suite without secrets. Test-only fixtures/mocks are not production integration implementations.

Back up SQLite and media together before upgrading. Migrations are additive; no normal startup deletes data. New databases use foreign keys; non-destructive reference/timing triggers also protect legacy tables. After initializing/upgrading, run `python -m scripts.audit_db` to report legacy orphan/invalid records without modifying them.

Never commit `.env`, secrets, OAuth tokens, model binaries, private media, or a local `whisper.cpp/` checkout. Prior generated files are retained by default; stop the app and run `python -m scripts.cleanup_media` for a safe dry-run of unreferenced old generated outputs, adding `--apply` only after review. Failed render temporary directories and partial voice files are cleaned.


Local AI/render UI actions use the persistent task queue. The Local Processing History panel remains available after reload/disconnection. Failed/interrupted tasks may be retried as new tasks; published jobs never use this local-task retry mechanism. `SCHEDULER_ENABLED=true` is required for queued work.

Default/YouTube/test dependencies are constrained by `backend/constraints.txt`. Optional Argos uses its separately declared dependency file and must be validated with the chosen locally installed language packages.
