# Official platform integrations

No real publication was performed in the audit environment. Contract tests intercept HTTP calls; they are not platform approval or live-upload verification.

## Facebook

Configure `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_ACCESS_TOKEN`, and a supported `FACEBOOK_GRAPH_VERSION`. Obtain official Page permissions and token authorization through Meta. Tokens remain server-side. Images use Page photo uploads. The queue currently routes all videos to Reels; general video-vs-Reel selection and format eligibility validation remain limitations.

Reels: Graph `/{page}/video_reels` start → returned HTTPS `rupload.facebook.com` URL with OAuth/offset/file_size headers and streaming binary transfer → Graph finish with video_state=PUBLISHED. An explicit success response is required. Final asynchronous processing is not polled by this adapter; acceptance is not proof of eventual visibility. Verify platform history, especially after uncertainty.

## YouTube

Install `backend/requirements-youtube.txt`. Download an official Desktop OAuth client configuration to `YOUTUBE_CLIENT_SECRETS_FILE`. On the owner's local machine with browser access, run:

```bash
python -m backend.app.integrations.youtube
```

This is the explicit official installed-app OAuth flow. The scheduler never opens a browser or waits on an interactive OAuth callback. Securely provision the resulting `YOUTUBE_TOKEN_FILE` on the host/container; it is never returned to the UI. Refreshed tokens are persisted with mode 0600 via an atomic replacement. Revoked/missing authorization needs this flow again, not a credential bypass.

Uploads use `videos.insert`, resumable upload support, title/description/hashtag tags and configured privacy. Future `publishAt` forces private upload, as required. Such jobs are labeled **UPLOADED**, not falsely asserted publicly visible; post-upload processing/publication is not polled. Keywords are not currently routed as separate tags. Shorts classification is performed by YouTube, not a special Shorts upload endpoint. Quotas, audits/private-upload restrictions and copyright checks still apply.

## TikTok

Provide an authorized Content Posting API `video.publish` access token. Load creator info in the UI, select one of the returned privacy options explicitly, and give per-job publishing/media-rights consent. The job stores this choice; creator info is checked again before initialization. Comments/duet/stitch honor creator-disabled flags.

Direct Post flow: creator_info/query → video/init with FILE_UPLOAD → HTTPS chunk uploads (last chunk absorbs remainder) → persist publish_id → status/fetch until explicit completion/failure. Chunk sizes obey the implemented 10 MB base size; upload hosts are restricted to TikTok domains and redirects are not followed. Tokens are provisioned through official authorization outside this application; built-in TikTok OAuth/refresh is not implemented.

Unaudited client restrictions, including private-only viewing where imposed, remain in force. A privacy choice is not permission to bypass audit restrictions. This owner-only tool may not qualify for public Direct Post approval; do not assume approval merely because the API adapter exists. Duration/creator maximum checks, full per-post interaction/disclosure controls, and comprehensive platform review UX remain incomplete.

## Uncertain outcomes

An API timeout can occur after acceptance. The queue records REVIEW_REQUIRED and will not upload again automatically. Check the platform history, then use **Reconcile outcome**, recording a verified ID or confirmed absence and a note. This is an explicit human attestation recorded in history, not a fabricated platform response.
