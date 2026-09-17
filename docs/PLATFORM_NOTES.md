# Official platform integrations

Use only official app credentials, permissions, consent, quotas and platform approvals. No website automation, scraping publication, credential bypass or simulated platform success is implemented. No live owner-account publication was performed by the test suite.

## Facebook

Configure a Page ID/token and supported Graph API version, either through environment defaults or an account profile. Select standard photo/video post or Reel per scheduled job. Source images use photo upload; rendered image MP4s use video/Reel handling.

Reels use Graph `/{page}/video_reels` start, returned HTTPS `rupload.facebook.com` binary transfer with OAuth/offset/file_size headers, and Graph finish. Video jobs remain PUBLISHING while their official status is polled. Reels require both ready video state and completed publishing phase. Platform errors/deadlines remain visible; a finish response alone is not treated as eventual publication proof.

The selected Graph API remains authoritative for eligibility, evolving duration/format requirements and permissions. Locally valid media is not a guarantee the platform will accept publication. If an outcome is uncertain, inspect the Page dashboard before reconciliation.

## YouTube

Install `requirements-youtube.txt`, configure a Desktop OAuth app and explicitly authorize the desired profile with:

```bash
python -m backend.app.integrations.youtube --account-key default
```

Upload and readonly scopes support both submission and subsequent processing checks. Upload-only legacy authorizations may need reauthorization. OAuth never launches from the queue worker. Token refresh is file-locked and persisted atomically with restrictive permissions.

Uploads use resumable chunks, title/description, hashtag plus keyword tags, and explicit privacy. Only **public** schedules upload early and use private upload plus `publishAt`. Private/unlisted schedules upload at the requested time without native public scheduling. If an early public upload becomes late during authorization, it no longer sends a past `publishAt`.

UPLOADED jobs poll `videos.list` status/processingDetails. They become PUBLISHED only after processing and expected visibility are verified. Explicit rejection/failure is retained, while unresolved states reach a bounded review deadline. Public visibility can remain restricted by unverified-project rules; code does not bypass this restriction.

Shorts is classified by YouTube based on its rules, not a separate upload endpoint. Copyright, quota, project review and channel authorization remain external requirements.

## TikTok

`ACCOUNTS.md` documents official Login Kit OAuth, state verification, code exchange and automatic rotating token refresh. A configured environment access token remains supported, but refreshing it requires official app/token-file setup.

Select the account, load creator information, choose privacy explicitly and confirm publishing/media/music rights. Per-job controls include comments/duet/stitch, own-brand promotion, third-party branded content and AI-content disclosure. Creator-disabled interaction flags cannot be enabled by a job. Branded content cannot select SELF_ONLY. Creator information and maximum duration are checked again when uploading.

Direct Post uses creator_info/query, video/init FILE_UPLOAD, bounded HTTPS chunks whose last chunk absorbs the remainder, and status/fetch until explicit success/failure. A polling deadline moves unresolved jobs to REVIEW_REQUIRED instead of silently waiting forever or re-uploading.

Official app approval, creator limits and unaudited/private-only restrictions remain in force. An owner-only tool may not qualify for public Direct Post approval; implementing the endpoints does not guarantee approval or full platform review acceptance. Review the current platform terms and UX requirements for your deployment.

## Reconciliation

A request can be accepted remotely even if the client loses its response. The queue does not blindly retry an uncertain result. Use **Reconcile outcome** only after checking the actual platform history; record the verified remote ID or confirmed absence and a note. This is labeled owner verification, never a fabricated API result.

## Reference endpoints

- YouTube video resource/status: https://developers.google.com/youtube/v3/docs/videos
- TikTok Direct Post: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- TikTok OAuth/token management: https://developers.tiktok.com/doc/oauth-user-access-token-management
- Meta Reels publishing: https://developers.facebook.com/docs/video-api/guides/reels-publishing/
