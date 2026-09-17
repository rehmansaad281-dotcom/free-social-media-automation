# Repository audit and implementation report

Date: 2026-09-17. Branch: `arena/01a0b09d-free-social-media-automation`.

## 1. COMPLETED

The complete initial repository was inventoried and read **before changes**: all 29 tracked files, 4,450 lines, including every Python/frontend file, dependencies, environment example, Docker/Compose, CI, scripts, README and documentation. No tests existed initially. Existing FastAPI/SQLAlchemy/HTML architecture and real platform adapters were retained rather than replaced with a demo.

Implemented:

- Fail-closed owner Basic authentication, same-origin mutation checks, safe public dependency errors, path containment and removal of private filesystem fields from API responses.
- Upload extension/MIME checks augmented by restricted-protocol/format FFprobe inspection, image-codec checks, video duration checks, generated filenames, size limits and failure cleanup.
- Correct whisper.cpp full-JSON parsing, executable resolution, subprocess timeouts, millisecond-preserving word aggregation, and explicit missing-speech/timing/dependency errors.
- Independent transcription/caption persistence and metadata-only regeneration. Ollama timeout, malformed-response and field-type handling.
- Optional actual local Argos translation with explicit dependency/language-package errors; preserved Ollama translation default.
- Piper availability requires model plus readable configuration; no guessed gender availability. Timeout and nonempty WAV validation; failure cleanup and authenticated voice-audio endpoint.
- Audio provenance for captions and a voice-over retranscription endpoint/UI control, so original timings are not silently reused for translated narration.
- Unique temporary/final rendering paths; H.264/yuv420p/AAC normalization, faststart, padded short narration, safe subtitle filter paths, preserved originals, authenticated range-capable preview.
- Caption validation for blank/negative/zero-duration/overlapping/duplicate cues and stale editor/content protection.
- Draft updates instead of unintended new records, synchronized content IDs/metadata/voice text, metadata retry controls, loading states for static actions, repaired caption deletion and meaningful API errors.
- UTC schedule validation, serialized duplicate schedule checks on SQLite, atomic queue claims, durable per-attempt history, safe retries, restart review state and explicit owner reconciliation.
- Published/in-flight jobs cannot be retried blindly; attempted history cannot be deleted. Content with active jobs cannot be edited through normal endpoints.
- Facebook Reel transfer through its returned official upload URL with streamed data and required headers.
- YouTube interactive OAuth moved out of the scheduler into an explicit setup command; token refresh persistence/permissions, input privacy/title validation, accurate UPLOADED labeling for future publishAt.
- TikTok last-chunk remainder correction, strict creator privacy validation, upload URL checks, explicit per-job privacy/consent UI and content status update after completion.
- Additive migrations, fresh-schema foreign keys, SQLite WAL/busy timeout and read-only legacy integrity audit.
- Non-root Docker user, private default port binding, explicit executable/model mounts, YouTube dependency installation, updated setup documentation and test-running CI.
- 52 automated test cases collected, with 51 passing and 1 dependency-based skip in this environment.

## 2. BUGS FIXED — ROOT CAUSES

| Bug | Root cause / correction |
|---|---|
| Incorrect transcript and missing word captions | Parser stringified `transcription` and looked for `segments`; now reads whisper.cpp's transcription array and token millisecond offsets. |
| Overlapping generated short captions | Route artificially extended cues to 50 ms; now preserves validated timings. |
| Losing transcription when metadata failed | One transaction depended on both AI services; transcript/captions now persist first. |
| Accepting invalid Ollama fields | Arbitrary values were converted to strings; now field types are validated. |
| Wrong caption timing with voice-over | Original timestamps were burned onto new speech; captions track their audio source and can be regenerated from the actual WAV. |
| False available voices/gender | Filename heuristics and model-only checks; require config and use declared metadata or unknown. |
| Corrupted/stale repeated render output | Shared deterministic output filenames; unique outputs and temporary directories now isolate attempts. |
| Short voice cut the video short | `-shortest` without padding; audio is now padded first. |
| Browser-incompatible rendered MP4 | Stream copying arbitrary input codecs; normalize to H.264/AAC/yuv420p with faststart. |
| FFmpeg subtitle path escaping failures | Arbitrary absolute paths embedded in filter syntax; fixed local SRT filename in isolated working directory. |
| Spoofed media accepted | Only MIME/extension were checked; actual probing added (real FFprobe run still unverified here). |
| Local filesystem paths exposed | ORM/raw path fields returned directly; public record projection and authenticated URLs added. |
| Unauthenticated private media/publishing controls | No access control; owner authentication now required. |
| Duplicate draft instead of saving edits | UI always POSTed; loaded drafts now PATCH. |
| Caption delete targeted wrong row | Index handlers became stale after deletion; delete the clicked DOM row directly. |
| Empty retry/reconcile JSON objects | SQLAlchemy attributes expired after commit; refresh/project before serialization. |
| Duplicate publishing from retries | Any job, including PUBLISHED, could be queued again; status/external-ID guards added. |
| Duplicate worker claim | In-memory status assignments were not a cross-session claim; conditional SQL update added and concurrent-worker test passes. |
| Interrupted job disappeared indefinitely | No restart policy for interrupted PUBLISHING; now REVIEW_REQUIRED, preserving uncertainty. |
| Lost publishing attempt history | Only latest job error/attempt count persisted; separate attempt journal added. |
| Wrong Facebook Reel transfer endpoint | Transfer was sent back to Graph initialization endpoint; now uses returned rupload URL. |
| Scheduler blocked on OAuth browser | YouTube authorization was initiated in worker; explicit setup command now required. |
| Refreshed YouTube token not saved | Persistence occurred only after fresh authorization; valid refreshed tokens now persist atomically. |
| TikTok invalid final small chunk | Ceiling division created an undersized extra chunk; final planned chunk absorbs remainder. |
| TikTok content remained stale after success | Poller updated Job but not Content; both update on completion. |
| Documentation/CI mismatched implementation | Docs claimed faster-whisper/Argos-only behavior and CI ran no tests; docs reflect actual selectable stack, CI runs regression/structure checks. |

## 3. FILES CHANGED

| File | Reason |
|---|---|
| `.dockerignore` | Exclude local whisper.cpp checkout and test cache. |
| `.gitignore` | Prevent committing whisper.cpp and test cache. |
| `.env.example` | Document authentication, FFprobe, timeout, scheduler and translation backend settings. |
| `.github/workflows/ci.yml` | Install test dependencies, check dependency consistency, execute tests and frontend/structure validation; remove compiled cache from artifact. |
| `Dockerfile` | Install YouTube extras and run as non-root UID/GID 10001. |
| `docker-compose.yml` | Loopback host binding and explicit read-only model/executable mounts. |
| `README.md` | Accurate workflow, secure startup, Docker/runtime/test instructions and readiness caveats. |
| `backend/app/config.py` | Authentication/runtime settings and bounded/enum configuration validation. |
| `backend/app/db.py` | Configured SQLite parent directory, WAL/foreign keys/busy timeout and additive migrations. |
| `backend/app/models.py` | Fresh-schema foreign keys, caption audio provenance, job privacy choice and durable attempt journal. |
| `backend/app/schemas.py` | TikTok privacy/consent and validated reconciliation request. |
| `backend/app/errors.py` | New safe public diagnostic sanitization. |
| `backend/app/main.py` | Lifecycle/authentication, safe upload/response handling, separate AI actions, captions/audio/render consistency, queue guards/history/reconciliation. |
| `backend/app/media.py` | Real FFprobe interface, media normalization, timeout/padded voice and safe subtitle processing. |
| `backend/app/ai/transcription.py` | Correct full-JSON parser, subword aggregation, timestamp checks, executable resolution/timeouts. |
| `backend/app/ai/content.py` | Ollama timeout, service failure and JSON schema checks. |
| `backend/app/ai/translation.py` | Local Argos option, language/empty input validation and strict translation response types. |
| `backend/app/ai/tts.py` | Real voice availability/config metadata, timeout and WAV validation. |
| `backend/app/scheduler.py` | Atomic claims, safe retry/restart policies, attempt journal and status consistency. |
| `backend/app/integrations/facebook.py` | Correct official Reel binary transfer and success validation. |
| `backend/app/integrations/youtube.py` | Explicit OAuth setup, refreshed token persistence, privacy/title validation and sanitized upload errors. |
| `backend/app/integrations/tiktok.py` | Creator privacy, JSON/upload host validation and correct remainder chunking. |
| `backend/requirements-argos.txt` | Declare optional real Argos dependency. |
| `backend/requirements-test.txt` | Declare test stack and YouTube extras for integration contract tests. |
| `frontend/index.html` | Draft/edit synchronization, AI retry/voice-caption controls, loading/errors, privacy/consent, history/reconciliation and safe job controls. |
| `docs/ARCHITECTURE.md` | Full execution/dependency map and state/transaction boundaries. |
| `docs/SETUP_LOCAL_AI.md` | Actual whisper.cpp, Piper, FFmpeg and selectable translation setup. |
| `docs/PLATFORM_NOTES.md` | Official API flow, explicit setup and platform-specific restrictions/limitations. |
| `docs/AUDIT_REPORT.md` | This report, evidence, checklist and readiness decision. |
| `scripts/audit_db.py` | Read-only orphan/duplicate/invalid legacy database report. |
| `scripts/check_structure.py` | Python AST, frontend ID/JS syntax and deployment structure checks. |
| `tests/conftest.py` | Isolated test database/media, authentication and executable fixtures. |
| `tests/test_api.py` | Authentication, CRUD, upload contract/failures, caption transactions, AI failures, scheduling, reconciliation, actual render/preview contract. |
| `tests/test_ai_media.py` | Whisper/Ollama validation, translation/voice availability, SRT and actual FFmpeg pipeline checks. |
| `tests/test_scheduler_integrations.py` | Queue claims/restart/retries/history and official HTTP request contracts; no real posts. |
| `tests/test_database.py` | Idempotent additive legacy migration and record preservation. |

Unchanged requirements were also audited: base third-party imports are declared in `backend/requirements.txt`; Google imports are declared in existing optional `backend/requirements-youtube.txt`. No model/media binaries, credentials, unrelated project, or user data were committed. The audit was initially delivered as local changes; commit/push and a pull request were subsequently authorized by the owner.

## 4. TEST RESULTS

Final local checks:

| Exact command | Result |
|---|---|
| `.venv/bin/python -m pytest -q` | **51 passed, 1 skipped**; 2 upstream Starlette/httpx/AnyIO deprecation warnings. |
| `.venv/bin/python -m compileall -q backend scripts tests` | Passed. |
| `.venv/bin/python scripts/check_structure.py` | Passed: Python AST, unique/referenced HTML IDs, Node JavaScript syntax and required structure. |
| `.venv/bin/pip check` | Passed: no broken requirements. |
| `git diff --check` | Passed. |
| `.venv/bin/python -c 'from backend.app.main import app; print(len(app.routes))'` | Import passed during implementation; final tests also import and run application lifespan. |

**CODE VERIFIED:** TestClient application startup/database initialization; authenticated endpoints; invalid inputs; atomic caption saves; AI dependency errors; no duplicate published-job retries; two-worker atomic queue claim; restart recovery; migration preservation; attempt journal; reconciliation; real FFmpeg normalization, audio replacement, subtitle burning, full decode, repeated render preservation; HTTP preview and byte-range responses. HTTP contract tests verify Facebook/TikTok calls but do not contact platforms.

**RUNTIME DEPENDENCY NOT AVAILABLE:** FFprobe; whisper.cpp executable/model; Ollama service/model; Piper executable/model; Argos models/runtime; platform credentials/authorization. The real FFprobe test is the one explicit skip. Upload API tests exercise a mocked probe boundary and rejection/cleanup, not a claim that real FFprobe acceptance passed.

FFmpeg was initially missing. Debian package installation failed due sandbox network access. A test-only `imageio-ffmpeg` wheel supplied an actual executable (inside ignored `.venv`) for real render tests. It is not an application dependency or a substitute implementation of FFprobe.

Docker executable was absent; image build and Compose runtime were **not run**. GitHub-hosted CI was updated but not triggered/run remotely. No interactive browser automation or visual cross-browser playback testing was performed; Node syntax checks and HTTP/media decoding tests are not a substitute for that.

## 5. REMAINING EXTERNAL REQUIREMENTS

- FFmpeg/FFprobe installation in the deployment environment; Linux-compatible AI executables/native libraries for Docker.
- whisper.cpp GGML model, Piper voice model/config, and an available Ollama service/model; optional Argos package and installed language pairs.
- Owner-provided official Facebook Page credentials/permissions.
- Official YouTube client credentials, explicit OAuth authorization, quota and any required project approval.
- Official TikTok token authorization, required scopes and platform approval/audit where applicable. Platform restrictions cannot be bypassed by this code.
- Deployment environment with Docker if container deployment is used, HTTPS/private networking and writable persistent storage.

## 6. KNOWN LIMITATIONS / INCOMPLETE COMPONENTS

These are software or verification gaps, **not merely missing credentials**:

1. **Platform completion:** Facebook asynchronous Reel processing is not polled; YouTube future uploads remain UPLOADED without eventual publication verification. Facebook video-vs-Reel selection/eligibility, YouTube keyword tag routing, and TikTok creator duration checks and full disclosure/interaction-control UX remain incomplete.
2. **TikTok authorization lifecycle:** Token configuration is supported, but built-in OAuth/token refresh is not implemented. Long-lived unsuccessful status polling has no bounded reconciliation deadline.
3. **Account routing:** One credential set per platform per instance; the legacy account table is not a functional multi-account selector.
4. **Concurrency:** Queue claims are atomic and tested, but media work is not a durable worker queue. Same-content concurrent edits/renders and multiple scheduler process startup are not fully serialized. One worker/owner operation at a time is the supported deployment constraint, not a multi-worker production claim.
5. **Legacy integrity:** Fresh schemas have foreign keys; legacy tables are not rebuilt. Existing orphan/duplicate records are reported, not silently destroyed/repaired. Existing malformed/overlapping captions may need repair before rendering.
6. **Media/storage:** No image-to-video rendering; voice longer than video is trimmed; previous successful outputs are retained without automatic garbage collection. Resource/duration/resolution limits beyond upload size and subprocess timeout need further operational hardening for large/untrusted workloads.
7. **Language/voice:** Word grouping is whitespace-based and needs real-model validation for non-whitespace languages. Piper multi-speaker selection is not implemented. Synthesized audio and model quality were not tested here.
8. **Validation coverage:** Real FFprobe upload acceptance, live AI output, live publishing, Docker startup and interactive browser end-to-end behavior are not verified. Test dependency ranges currently resolve with two deprecation warnings; a fully pinned/reproducible deployment lock is not provided.

No simulated success responses or fake AI/publishing implementations were added to production modules. Owner reconciliation is explicitly labeled and journaled as human verification, not an API result.

## 7. FINAL STATUS

**NOT READY**

The repository is substantially repaired and has repeatable passing regression checks, but the requested production acceptance is not met. Exact blockers are the incomplete platform completion/token/eligibility workflows, unsupported multi-account routing and fully durable/concurrency-safe media processing, plus the unperformed real FFprobe/AI/platform/Docker/browser end-to-end verification listed above. Missing models/credentials alone are not being used to conceal those remaining software gaps.
