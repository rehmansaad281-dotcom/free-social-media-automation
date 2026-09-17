# Follow-up implementation and verification

This report supersedes the incomplete-component list in the historical `AUDIT_REPORT.md`.

## Implemented in this follow-up

- **Durable media/AI tasks:** UI submits to `/api/tasks`; persisted jobs run outside request handling, survive browser disconnect, expose status/results/history and offer explicit failed-task retry. Interrupted RUNNING tasks become visible FAILED records at restart. Existing synchronous endpoints remain compatible.
- **Concurrency:** a cross-process runtime lock enforces one application/scheduler on this single-host SQLite deployment. Per-content filesystem locks serialize mutations, rendering, task submission, scheduling and publishing-history actions. Queued/running media tasks block edits/scheduling until complete.
- **Multiple accounts:** safe server-side JSON profiles, context-local credential routing, account dropdown and immutable per-job profile keys for uploads/polls. Credentials are never returned by account APIs. See `ACCOUNTS.md`.
- **Completion polling:** Facebook video/Reel uploads remain PUBLISHING until readiness (and Reel publishing-phase completion). YouTube uploads remain UPLOADED until processing and expected privacy/publication are verified. Explicit platform failure remains in history. Every platform has a bounded polling deadline, then REVIEW_REQUIRED without re-upload.
- **TikTok OAuth:** official Login Kit authorization URL, single-use expiring state, server-side code exchange, permission check, access-token refresh and atomic restrictive token storage. Per-account token files are supported.
- **Per-post controls:** Facebook post/video versus Reel choice; YouTube privacy and keyword/tag integration; TikTok creator-duration validation, privacy/consent, interaction-disable flags, brand disclosures and AI-generated disclosure. Creator-disabled interaction flags cannot be overridden.
- **Media/voices:** still-image MP4 rendering, image preview, configurable image duration, optional final-frame extension instead of cutting longer narration, model speaker selection, bounded duration/resolution/FFmpeg threads, strict legacy caption validation and offline dry-run-first generated-output cleanup.
- **Legacy integrity:** SQLite trigger guards enforce new reference integrity even on existing tables, without destructive rebuilds; pre-existing duplicate active jobs are quarantined for review rather than republished. Existing ambiguous/corrupt owner records are not automatically invented, discarded or reassigned.
- **Security:** authentication is checked before multipart body parsing; content-length limits, thread-offloaded probing, non-reflected platform errors, isolated account settings and secret-free account responses. OAuth query logging is disabled in provided startup commands.
- **Reproducibility/CI:** tested default/YouTube/test dependency constraints, expanded regression suite, Docker build and an actual in-container FFprobe/upload/rejection/render/preview smoke test.

## Verification evidence

Local test/check results and GitHub CI results are recorded after final execution below. Live platform posts, local AI model quality, platform approvals and interactive browser behavior are not inferred from contract tests.

## Operational boundaries (not bypasses)

- One host, one application process and shared persistent SQLite/media/lock storage are intentional enforced deployment constraints. This is not distributed SaaS infrastructure.
- Credentials, official authorization/approval, locally installed models/executables and a reachable Ollama service still must be supplied by the owner. No paid API, browser-based publishing automation or simulated success is used.
- Existing corrupt/orphan records need owner-informed repair; read-only audit and safe reference guards avoid destroying data. Automatic reassignment would invent the owner's intent.
- Whitespace-free language segmentation and actual speech/translation quality depend on real model outputs and remain subject to validation with the chosen languages/models. The existing word aggregation is not a universal linguistic word segmenter.
- Animated GIF-to-video conversion is explicitly rejected; upload an actual video or supported still image. Rendered MP4s can be published even when their source was an image.
- Resource defaults are configurable safeguards, not a hostile multi-tenant upload sandbox. Run privately as a restricted OS user, with HTTPS/VPN and storage quotas.
- Platform eligibility beyond local checks remains enforced by the actual APIs. Approval is not guaranteed by implementing their endpoints.

## Status

**NOT READY for a fully verified production sign-off** until real configured AI/platform workflows and interactive browser acceptance are exercised. This is a verification boundary, not a claim that missing credentials are fabricated or that live publishing passed.

### Local execution (this follow-up)

- `.venv/bin/python -m pytest -q`: **73 passed, 1 skipped**, two upstream deprecation warnings. The skip is real FFprobe availability in the sandbox; actual FFmpeg tests use the test-only imageio-ffmpeg executable.
- `.venv/bin/python -m compileall -q backend scripts tests`: passed.
- `.venv/bin/python scripts/check_structure.py`: passed.
- `.venv/bin/pip check`: passed.
- `git diff --check`: passed.
- Original PR CI run `35260864553`: passed before this follow-up; does not substitute for checking the new commit.

The newly added Docker smoke check and updated regression CI must pass on the pushed follow-up commit. Their observed results will be recorded separately; no remote success is assumed here.
