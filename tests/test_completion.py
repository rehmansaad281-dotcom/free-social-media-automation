import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from filelock import FileLock
from sqlalchemy.exc import IntegrityError

from backend.app import main, scheduler, tasks
from backend.app.accounts import account_context, list_accounts, profile
from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.integrations import tiktok_auth, tiktok
from backend.app.models import Content, Job, MediaTask, PublicationAttempt
from backend.app.schemas import TaskRequest
from tests.test_api import seed
from tests.test_scheduler_integrations import add_job


def test_task_is_durable_and_resumable(client, monkeypatch):
    cid = seed()
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(main, "generate_metadata", lambda *args: {"title": "Updated", "description": "Description", "hashtags": "#tag", "keywords": "topic"})
    result = client.post("/api/tasks", json={"content_id": cid, "action": "metadata"})
    assert result.status_code == 202
    tid = result.json()["id"]
    assert client.patch(f"/api/content/{cid}", json={"title": "race"}).status_code == 409
    assert client.post("/api/tasks", json={"content_id": cid, "action": "metadata"}).status_code == 409
    tasks.execute_media_tasks()
    assert client.get(f"/api/tasks/{tid}").json()["status"] == "SUCCEEDED"
    assert client.get(f"/api/content/{cid}").json()["title"] == "Updated"
    tasks.execute_media_tasks()  # no duplicate execution


def test_task_failure_and_explicit_retry(client, monkeypatch):
    cid = seed()
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    def fail(*args): raise RuntimeError("Ollama unavailable")
    monkeypatch.setattr(main, "generate_metadata", fail)
    tid = client.post("/api/tasks", json={"content_id": cid, "action": "metadata"}).json()["id"]
    tasks.execute_media_tasks()
    assert client.get(f"/api/tasks/{tid}").json()["error"] == "Ollama unavailable"
    response = client.post(f"/api/tasks/{tid}/retry")
    assert response.status_code == 202 and response.json()["id"] != tid


def test_interrupted_task_recovery():
    cid = seed()
    with SessionLocal() as db:
        db.add(MediaTask(content_id=cid, action="render", status="RUNNING")); db.commit()
    tasks.recover_media_tasks()
    with SessionLocal() as db:
        task = db.query(MediaTask).one()
        assert task.status == "FAILED" and "Retry" in task.error


def test_content_mutation_lock(client):
    cid = seed()
    lock = Path(settings.lock_dir) / f"content-{cid}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock)):
        assert client.patch(f"/api/content/{cid}", json={"title": "racing"}).status_code == 409


def test_named_accounts_are_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "accounts_dir", str(tmp_path))
    monkeypatch.setattr(settings, "facebook_page_id", "base")
    (tmp_path / "facebook-page2.json").write_text(json.dumps({"name": "Second page", "settings": {
        "facebook_page_id": "second", "facebook_page_access_token": "private-profile-token"}}))
    listed = list_accounts()
    assert any(item["key"] == "page2" for item in listed)
    assert "private-profile-token" not in json.dumps(listed)
    with account_context("facebook", "page2"):
        assert settings.facebook_page_id == "second"
    assert settings.facebook_page_id == "base"
    with pytest.raises(ValueError): profile("facebook", "../escape")


def test_context_is_thread_local(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(settings, "accounts_dir", str(tmp_path))
    for key in ("a", "b"):
        (tmp_path / f"facebook-{key}.json").write_text(json.dumps({"name": key, "settings": {
            "facebook_page_id": key, "facebook_page_access_token": key}}))
    def read(key):
        with account_context("facebook", key):
            return settings.facebook_page_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(read, ("a", "b"))) == ["a", "b"]


def test_tiktok_oauth_state_single_use(monkeypatch, tmp_path):
    from urllib.parse import parse_qs, urlsplit
    monkeypatch.setattr(settings, "accounts_dir", str(tmp_path / "accounts"))
    monkeypatch.setattr(settings, "tiktok_client_key", "test-client")
    monkeypatch.setattr(settings, "tiktok_redirect_uri", "https://owner.example/api/tiktok/oauth/callback")
    url = tiktok_auth.authorization_url("default")
    state = parse_qs(urlsplit(url).query)["state"][0]
    assert tiktok_auth.consume_state(state) == "default"
    with pytest.raises(ValueError): tiktok_auth.consume_state(state)


def test_tiktok_refresh_rotation_persisted(monkeypatch, tmp_path):
    path = tmp_path / "token.json"
    monkeypatch.setattr(settings, "tiktok_token_file", str(path))
    monkeypatch.setattr(settings, "tiktok_client_key", "client")
    monkeypatch.setattr(settings, "tiktok_client_secret", "secret")
    tiktok_auth.save_private(path, {"access_token": "old", "refresh_token": "refresh-old", "expires_at": 1})
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"access_token": "new", "refresh_token": "refresh-new", "expires_in": 86400, "scope": "video.publish"})
    monkeypatch.setattr(tiktok_auth.httpx, "post", post)
    assert tiktok_auth.access_token() == "new"
    assert tiktok_auth.access_token() == "new"
    assert len(calls) == 1 and calls[0]["data"]["grant_type"] == "refresh_token"
    assert json.loads(path.read_text())["refresh_token"] == "refresh-new"
    assert path.stat().st_mode & 0o777 == 0o600


def test_tiktok_missing_scope_rejected(monkeypatch):
    monkeypatch.setattr(settings, "tiktok_client_key", "client")
    monkeypatch.setattr(settings, "tiktok_client_secret", "secret")
    monkeypatch.setattr(tiktok_auth.httpx, "post", lambda url, **kw: httpx.Response(200, request=httpx.Request("POST", url), json={"access_token": "x", "refresh_token": "r", "scope": "user.info.basic"}))
    with pytest.raises(RuntimeError, match="scope"): tiktok_auth._exchange({})


@pytest.mark.parametrize("platform", ["facebook", "youtube", "tiktok"])
def test_bounded_platform_polling(platform):
    jid = add_job(platform)
    with SessionLocal() as db:
        job = db.get(Job, jid)
        job.status = "UPLOADED" if platform == "youtube" else "PUBLISHING"
        job.external_id = "remote"
        job.publish_at = job.last_attempt_at = job.created_at = datetime.utcnow() - timedelta(days=3)
        db.commit()
    if platform == "tiktok": scheduler.poll_tiktok_jobs()
    else: scheduler.poll_platform_jobs()
    with SessionLocal() as db:
        job = db.get(Job, jid)
        assert job.status == "REVIEW_REQUIRED" and job.external_id == "remote"


def test_youtube_pending_until_public(monkeypatch):
    from backend.app.integrations import youtube
    jid = add_job("youtube")
    with SessionLocal() as db:
        job = db.get(Job, jid)
        job.status = "UPLOADED"; job.external_id = "yt-id"
        job.last_attempt_at = job.publish_at - timedelta(minutes=5)
        db.commit()
    monkeypatch.setattr(youtube, "get_status", lambda _: {"status": {"uploadStatus": "processed", "privacyStatus": "private", "publishAt": "future"}})
    scheduler.poll_platform_jobs()
    with SessionLocal() as db: assert db.get(Job, jid).status == "UPLOADED"
    monkeypatch.setattr(youtube, "get_status", lambda _: {"status": {"uploadStatus": "processed", "privacyStatus": "public"}})
    scheduler.poll_platform_jobs()
    with SessionLocal() as db: assert db.get(Job, jid).status == "PUBLISHED"


def test_youtube_tag_keywords():
    from backend.app.integrations.youtube import metadata_tags
    assert metadata_tags("#hello #world", "hello, local AI") == ["hello", "world", "local AI"]
    with pytest.raises(ValueError): metadata_tags("#" + "a" * 501, "")


def test_tiktok_duration_checked_before_initialization(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"; path.write_bytes(b"test")
    monkeypatch.setattr(tiktok, "creator_info", lambda: {"privacy_level_options": ["SELF_ONLY"], "max_video_post_duration_sec": 60})
    monkeypatch.setattr(tiktok, "probe", lambda p: {"format": {"duration": 61}})
    with pytest.raises(ValueError, match="duration"): tiktok.publish_video(str(path), "Title")


def test_resource_limits(monkeypatch):
    from backend.app import media
    monkeypatch.setattr(media.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps({"streams": [{"width": 100000, "height": 100000}]})))
    with pytest.raises(ValueError, match="resolution"): media.probe("file.mp4")


def test_legacy_invalid_captions_not_silently_rendered(tmp_path):
    from backend.app.media import captions_to_srt
    with pytest.raises(ValueError, match="overlapping"):
        captions_to_srt([SimpleNamespace(start_ms=0, end_ms=100, text="first"), SimpleNamespace(start_ms=50, end_ms=200, text="second")], str(tmp_path / "out.srt"))


def test_piper_invalid_speaker_preflight(tmp_path):
    from backend.app.ai.tts import synthesize
    model = tmp_path / "voice.onnx"; model.touch()
    Path(str(model) + ".json").write_text(json.dumps({"num_speakers": 2}))
    with pytest.raises(ValueError, match="speaker"): synthesize("hello", str(tmp_path / "out.wav"), str(model), speaker_id=2)


def test_image_render_and_long_narration_extension(ffmpeg, tmp_path, monkeypatch):
    import subprocess
    from backend.app import media
    image = tmp_path / "image.png"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x120", "-frames:v", "1", str(image)], check=True)
    video = tmp_path / "still.mp4"
    media.image_to_video(str(image), str(video), 1)
    voice = tmp_path / "speech.wav"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", str(voice)], check=True)
    monkeypatch.setattr(media, "probe", lambda _: {"format": {"duration": "1"}})
    final = tmp_path / "extended.mp4"
    media.replace_audio(str(video), str(voice), str(final), extend_to_voice=True)
    result = subprocess.run([ffmpeg, "-i", str(final), "-f", "null", "-"], capture_output=True, text=True)
    assert result.returncode == 0 and "00:00:03." in result.stderr


def test_legacy_reference_guards():
    from sqlalchemy import text
    from backend.app.db import engine
    # Even a connection with SQLite FK enforcement disabled cannot add an orphan.
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            with pytest.raises(IntegrityError):
                connection.execute(text("INSERT INTO captions (content_id,start_ms,end_ms,text) VALUES (999,0,100,'orphan')"))
            connection.rollback()
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))


def test_unauthorized_upload_rejected_before_parsing(client):
    response = client.post("/api/media", content=b"malformed multipart", headers={"Content-Type": "multipart/form-data"}, auth=None)
    assert response.status_code == 401


def test_cleanup_never_removes_referenced_media(monkeypatch):
    import os
    from scripts.cleanup_media import candidates
    cid = seed()
    root = Path(settings.media_dir)
    old = root / "render_999_abcd1234.mp4"; old.write_bytes(b"old-output")
    os.utime(old, (1, 1))
    source = root / "seed.mp4"; os.utime(source, (1, 1))
    assert old in candidates(7) and source not in candidates(7)
    old.unlink()


@pytest.mark.parametrize("privacy", ["private", "unlisted"])
def test_youtube_nonpublic_schedule_never_uploads_early(privacy):
    now = datetime.utcnow()
    job = SimpleNamespace(platform="youtube", publish_at=now + timedelta(minutes=5), retry_at=None,
                          options_json=json.dumps({"youtube_privacy": privacy}))
    assert not scheduler._job_is_due(job, now)
    assert scheduler._job_is_due(job, now + timedelta(minutes=6))


def test_youtube_public_schedule_can_upload_early():
    now = datetime.utcnow()
    job = SimpleNamespace(platform="youtube", publish_at=now + timedelta(minutes=5), retry_at=None,
                          options_json=json.dumps({"youtube_privacy": "public"}))
    assert scheduler._job_is_due(job, now)
