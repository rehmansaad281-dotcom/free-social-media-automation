# Architecture and execution flow

## Runtime

Uvicorn → FastAPI lifespan → shared runtime file lock → SQLite schema/additive migrations/reference guards → APScheduler. One process owns this self-hosted database/media runtime; a second process fails clearly rather than running a duplicate scheduler. All instances targeting the same data must share `RUNTIME_LOCK_FILE` and `LOCK_DIR`.

SQLite uses WAL and a busy timeout. Fresh tables use foreign keys. Legacy tables gain non-destructive reference/timing triggers. Existing ambiguous data is retained for audit; duplicate active publication records are quarantined at startup.

## Browser and local processing

The HTML/JavaScript client uses same-origin authenticated API requests. Authentication precedes multipart parsing. Media uploads use generated filenames, byte limits, supported types, FFprobe stream validation and configurable duration/resolution limits. Private paths/credentials are not serialized; source/render/audio responses enforce MEDIA_DIR containment.

Heavy UI operations create persistent `MediaTask` rows: `QUEUED → RUNNING → SUCCEEDED/FAILED`. The scheduler processes these every two seconds. Tasks outlive browser disconnects, expose history/result/error, and can be retried as new records. Interrupted RUNNING tasks become FAILED on startup. Original synchronous APIs remain available for compatibility.

Per-content filesystem locks protect both synchronous calls and task execution. Other edits, task submissions and schedules are rejected while work is active. A task ContextVar identifies the currently executing task without bypassing competing task checks.

## AI/media flow

- Source video → FFmpeg mono 16 kHz PCM → whisper.cpp full JSON → transcript plus merged token offsets in milliseconds → Caption records. Transcript/captions commit independently of optional Ollama metadata.
- Ollama returns schema-validated title/description/hashtags/keywords. Translation uses configured Ollama or optional installed Argos packages.
- Piper uses a real local ONNX/config pair and optional validated speaker ID. Resulting WAV must contain samples.
- Voice captions retranscribe the actual generated WAV. Audio provenance prevents silently reusing original-audio timing on different narration.
- Rendering uses unique temporary files, normalized H.264/AAC/yuv420p MP4, optional audio replacement and libass captions, final FFprobe validation and a unique published local output reference. Source files are never overwritten.
- Still images can become timed MP4s. Short narration is padded; longer narration can extend the last frame or be trimmed explicitly. Legacy malformed captions are rejected, not silently burned.

## Publication

A `Job` stores Content ID, platform, account key, UTC time, privacy/options and retry budget. Schedules are serialized on SQLite and per-content locks; duplicate active/successful jobs are rejected per account. Worker claims use atomic SQL status comparison. Each remote attempt has a durable `PublicationAttempt` journal.

Credential routing uses context-local values from server-owned JSON profiles. Every upload and subsequent poll uses the job's original account key. Profile contents and token paths never reach the account dropdown.

- Facebook: selected photo/video post or Reel upload → PUBLISHING for video → poll readiness/publishing phase → PUBLISHED or FAILED.
- YouTube: public posts may upload up to ten minutes early with native `publishAt`; private/unlisted uploads start at the requested time and never get a public schedule. Uploads remain UPLOADED until processing/expected privacy is verified.
- TikTok: official OAuth/refresh or configured token → creator-info/limits check → explicit per-post privacy/disclosures/consent → Direct Post upload → poll explicit completion/failure.

Polling runs every minute. A deadline moves unresolved outcomes to REVIEW_REQUIRED without re-upload. Definite pre-request failures can back off/retry; uncertain remote results require explicit owner reconciliation. Published/in-flight jobs cannot be blindly retried and attempted history cannot be deleted.

Exactly-once external delivery cannot be guaranteed across a local database and non-transactional platform APIs. The queue preserves ambiguity and avoids duplicate uploads rather than claiming a distributed transaction.

## Storage and operational boundaries

One host/process and persistent shared locks are intentional—not a distributed worker cluster. Run privately as a restricted OS user with storage quotas and HTTPS/VPN. Offline `scripts.cleanup_media` is dry-run-first and only targets old, unreferenced generated filenames; original media and referenced outputs are retained. See `ACCOUNTS.md`, `FOLLOWUP_REPORT.md`, and the real CI smoke test for setup and verification boundaries.
