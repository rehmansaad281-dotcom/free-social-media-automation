# Architecture and execution flow

> The original execution map below is retained for context. Follow-up additions supersede its boundaries: durable `MediaTask` queue, per-content/runtime file locks, context-local multi-account profiles, and Facebook/YouTube completion polling. See `FOLLOWUP_REPORT.md` and `ACCOUNTS.md`.

## Entry points and dependencies

- `scripts/run.sh` / Uvicorn → `backend.app.main:app` → lifespan initializes SQLAlchemy schema/additive migrations and APScheduler. One scheduler process is supported.
- `config.py` reads `.env` with pydantic-settings. `db.py` configures SQLite WAL, foreign keys (new schema) and a 30-second busy timeout.
- Browser `frontend/index.html` uses same-origin JSON/multipart requests, Basic authentication, escaped user text, millisecond caption controls and UTC scheduling.
- `Media` stores a generated local filename and media type. Paths are never serialized to API clients and file responses enforce MEDIA_DIR containment.
- `Content` references source media and stores metadata, original transcript, translation, voice and render references. `Caption` stores integer milliseconds and audio provenance prevents mixing original/voice-over timing tracks.
- AI generation → extract mono 16 kHz PCM with FFmpeg → whisper.cpp full JSON → transcription segments/token offsets → merged word captions. Transcript/captions commit before optional Ollama metadata.
- Translation → configured Ollama or installed Argos language pair. Speech → installed Piper executable/model/config → validated nonempty WAV.
- Render → unique temporary directory → H.264/AAC normalization → optional padded voice replacement → optional SRT/libass burn → FFprobe → unique final MP4 → atomic content pointer update → authenticated range-capable preview.
- Schedule → validate content/platform/time/duplicates/TikTok consent → durable `Job`. SQLite scheduling uses an immediate transaction to serialize duplicate checks.
- APScheduler every 20 seconds → due jobs (YouTube begins up to 10 minutes early) → atomic SQL QUEUED→PUBLISHING claim → durable `PublicationAttempt` → official adapter. TikTok status polling runs every 60 seconds.

## Queue semantics

`QUEUED → PUBLISHING → PUBLISHED` (confirmed adapter response), or `UPLOADED` (YouTube accepted with future publishAt), or `REVIEW_REQUIRED` (uncertain request outcome).

Failures before a remote request can retry with bounded backoff. TikTok explicitly failed processing can retry; transport uncertainty cannot. Original `publish_at` is immutable, separate from `retry_at`. Each attempt has its own persistent record.

Restart converts interrupted PUBLISHING jobs without an external ID to REVIEW_REQUIRED. TikTok jobs with IDs resume polling. Owner reconciliation records a note and either a verified external ID or an explicit confirmed absence before a retry. History cannot be deleted through normal queue controls; only never-attempted queued jobs can be removed. Successful jobs cannot be retried.

Exactly-once delivery cannot be guaranteed across a local database and APIs with no shared transaction/idempotency key. The safe policy sacrifices unattended retry for uncertain results rather than risking duplicate posts.

## Boundaries

- Single owner and one credential set per platform. `PlatformAccount` and `VoiceProfile` legacy tables are not credential/account-routing implementations.
- Heavy work is synchronous in FastAPI worker threads, not a durable media-task queue. Avoid concurrent edits/renders of the same content and run one application worker. Queued/in-flight content is protected from normal edits.
- Foreign keys apply to fresh tables; legacy tables require read-only integrity audit and an explicit future repair migration if corrupt.
- Local AI executables, Docker model mounts, and platform approval are operational dependencies, not simulated services.
