from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from backend.app import scheduler as worker
from backend.app.db import SessionLocal
from backend.app.models import Job, Content, Media
from backend.app.config import settings
from backend.app.integrations import tiktok, facebook


def add_job(platform="facebook"):
    with SessionLocal() as db:
        path = Path(settings.media_dir) / "job.mp4"; path.write_bytes(b"fixture")
        media = Media(filename="job.mp4", path=str(path), media_type="video")
        db.add(media); db.flush()
        content = Content(media_id=media.id)
        db.add(content); db.flush()
        job = Job(content_id=content.id, platform=platform, publish_at=datetime.utcnow() - timedelta(minutes=1))
        db.add(job); db.commit()
        return job.id


def test_queue_runs_success_once(monkeypatch):
    jid = add_job(); calls = []
    monkeypatch.setattr(worker, "FacebookPublisher", lambda: SimpleNamespace(publish_reel=lambda *args: calls.append(args) or "remote-id"))
    worker.execute_due_jobs(); worker.execute_due_jobs()
    assert len(calls) == 1
    with SessionLocal() as db:
        job = db.get(Job, jid)
        assert job.status == "PUBLISHED" and job.attempts == 1


def test_uncertain_publication_not_retried(monkeypatch):
    jid = add_job()
    def fail(*args): raise TimeoutError("connection lost")
    monkeypatch.setattr(worker, "FacebookPublisher", lambda: SimpleNamespace(publish_reel=fail))
    worker.execute_due_jobs(); worker.execute_due_jobs()
    with SessionLocal() as db:
        job = db.get(Job, jid)
        assert job.status == "REVIEW_REQUIRED" and job.attempts == 1


def test_tiktok_completion_updates_content(monkeypatch):
    jid = add_job("tiktok")
    with SessionLocal() as db:
        job = db.get(Job, jid); job.status = "PUBLISHING"; job.external_id = "pid"; db.commit()
    monkeypatch.setattr(worker, "tiktok_status", lambda pid: {"status": "PUBLISH_COMPLETE"})
    worker.poll_tiktok_jobs()
    with SessionLocal() as db:
        job = db.get(Job, jid)
        assert job.status == "PUBLISHED"
        assert db.get(Content, job.content_id).status == "PUBLISHED"


def test_retry_preserves_original_time():
    job = SimpleNamespace(attempts=2, publish_at=datetime(2030, 1, 1))
    worker._schedule_retry(job, datetime(2030, 1, 2))
    assert job.publish_at == datetime(2030, 1, 1)
    assert job.retry_at == datetime(2030, 1, 2, 0, 4)


def test_tiktok_chunk_remainder(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"; path.write_bytes(b"x" * 21_000_000)
    monkeypatch.setattr(tiktok, "creator_info", lambda: {"privacy_level_options": ["SELF_ONLY"]})
    monkeypatch.setattr(settings, "tiktok_access_token", "test-only")
    payloads = []; chunks = []
    def post(url, **kwargs):
        payloads.append(kwargs["json"])
        return httpx.Response(200, json={"data": {"upload_url": "https://open-upload.tiktokapis.com/upload", "publish_id": "pid"}, "error": {"code": "ok"}})
    def put(url, **kwargs):
        chunks.append(len(kwargs["content"]))
        return httpx.Response(201)
    monkeypatch.setattr(tiktok.httpx, "post", post); monkeypatch.setattr(tiktok.httpx, "put", put)
    assert tiktok.publish_video(str(path), "title") == "pid"
    assert payloads[0]["source_info"]["total_chunk_count"] == 2
    assert chunks == [10_000_000, 11_000_000]


def test_tiktok_privacy_fails_closed():
    with pytest.raises(RuntimeError): tiktok._select_privacy({}, None)
    with pytest.raises(RuntimeError): tiktok._select_privacy({"privacy_level_options": ["SELF_ONLY"]}, "PUBLIC_TO_EVERYONE")


def test_facebook_real_transfer_contract(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"; path.write_bytes(b"video")
    monkeypatch.setattr(settings, "facebook_page_id", "page")
    monkeypatch.setattr(settings, "facebook_page_access_token", "test-only")
    requests = []
    def post(url, **kwargs):
        requests.append((url, kwargs))
        if len(requests) == 1:
            return httpx.Response(200, json={"video_id": "vid", "upload_url": "https://rupload.facebook.com/video-upload/vid"})
        if len(requests) == 2:
            assert b"".join(kwargs["content"]) == b"video"
        return httpx.Response(200, json={"success": True})
    monkeypatch.setattr(facebook.httpx, "post", post)
    assert facebook.FacebookPublisher().publish_reel(str(path), "d", "#t") == "vid"
    assert requests[1][0].startswith("https://rupload.facebook.com/")
    assert requests[1][1]["headers"]["file_size"] == "5"


def test_attempt_history_persisted(monkeypatch):
    from backend.app.models import PublicationAttempt
    jid = add_job()
    monkeypatch.setattr(worker, "FacebookPublisher", lambda: SimpleNamespace(publish_reel=lambda *args: "remote"))
    worker.execute_due_jobs()
    with SessionLocal() as db:
        attempt = db.query(PublicationAttempt).filter_by(job_id=jid).one()
        assert attempt.status == "PUBLISHED" and attempt.external_id == "remote"
        assert attempt.finished_at is not None


def test_missing_config_retries_without_losing_failure(monkeypatch):
    jid = add_job()
    monkeypatch.setattr(settings, "facebook_page_id", "")
    worker.execute_due_jobs()
    with SessionLocal() as db:
        job = db.get(Job, jid)
        assert job.status == "QUEUED" and job.retry_at and job.error
        assert job.attempts == 1


def test_youtube_missing_oauth_does_not_open_browser(tmp_path, monkeypatch):
    from backend.app.integrations import youtube
    monkeypatch.setattr(settings, "youtube_token_file", str(tmp_path / "missing.json"))
    with pytest.raises(RuntimeError, match="authorization required"):
        youtube.get_service()


def test_atomic_claim_across_workers(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    jid = add_job(); calls = []
    monkeypatch.setattr(worker, "FacebookPublisher", lambda: SimpleNamespace(publish_reel=lambda *args: calls.append(1) or "remote"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: worker.execute_due_jobs(), range(2)))
    assert calls == [1]
    with SessionLocal() as db:
        assert db.get(Job, jid).attempts == 1


def test_restart_marks_interrupted_job_for_review(monkeypatch):
    jid = add_job()
    with SessionLocal() as db:
        db.get(Job, jid).status = "PUBLISHING"; db.commit()
    monkeypatch.setattr(worker, "scheduler", SimpleNamespace(running=False, add_job=lambda *a, **k: None, start=lambda: None))
    worker.start_scheduler()
    with SessionLocal() as db:
        assert db.get(Job, jid).status == "REVIEW_REQUIRED"
