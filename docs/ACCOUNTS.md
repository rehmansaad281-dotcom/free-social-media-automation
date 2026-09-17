# Multiple accounts and official authorization

Each scheduled job stores `account_key` plus its platform and per-post options. Every upload and status poll resolves that same server-side profile. Account overrides are context-local, never process-global mutable credentials. Files are reread when used; do not reassign a profile key to a different account while jobs are active.

The `default` key uses existing environment settings. Additional profiles live under `ACCOUNTS_DIR` (default `./secrets/accounts`), with names `<platform>-<key>.json`. Keys contain only letters, digits, `_` and `-`. Protect the directory and JSON files with owner-only permissions. These files must never be committed. The browser receives only platform/key/display-name labels, never credential fields or token paths.

Example file shapes (replace values with your own official credentials on the server):

```json
{
  "name": "My second Facebook Page",
  "settings": {
    "facebook_page_id": "YOUR_PAGE_ID",
    "facebook_page_access_token": "YOUR_PAGE_TOKEN"
  }
}
```

Save as `facebook-second.json`; select it in the schedule account dropdown.

```json
{
  "name": "My second YouTube channel",
  "settings": {
    "youtube_client_secrets_file": "./secrets/youtube_second_client.json",
    "youtube_token_file": "./secrets/youtube_second_token.json",
    "youtube_default_privacy": "private"
  }
}
```

Save as `youtube-second.json`, then explicitly authorize on the owner's browser-capable machine:

```bash
python -m backend.app.integrations.youtube --account-key second
```

The authorization requests upload and readonly scopes so processing/publication can be verified. Previously issued upload-only tokens may need reauthorization. Provision separate token files per channel and never share a token file across accounts.

```json
{
  "name": "My second TikTok account",
  "settings": {
    "tiktok_token_file": "./secrets/tiktok_second_token.json",
    "tiktok_client_key": "YOUR_OFFICIAL_APP_CLIENT_KEY",
    "tiktok_client_secret": "YOUR_OFFICIAL_APP_CLIENT_SECRET",
    "tiktok_redirect_uri": "https://your-private-host.example/api/tiktok/oauth/callback"
  }
}
```

Save as `tiktok-second.json`. Register that exact HTTPS callback in TikTok Login Kit. Select TikTok and this account in the UI, then **Authorize Selected TikTok Account**. This redirects to TikTok's official authorization page, validates a single-use expiring state, exchanges the returned code server-side, and stores tokens with restrictive permissions. Revocation/expired refresh authorization requires consent again. Refresh tokens are rotated and saved atomically when needed.

The callback still requires owner Basic authentication. Use HTTPS and disable query-string access logging in the reverse proxy; authorization codes must not appear in logs. Provided server commands disable Uvicorn access logs for this reason. The browser returns no access/refresh token to JavaScript. Long-lived environment access tokens remain supported but cannot be refreshed without official OAuth app configuration.

Platform review/audit/permissions are still required. This implementation cannot make an owner-only client eligible for approval or bypass private-post restrictions. Read and comply with current platform terms before use.
