from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from backend.app import main
from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.models import Content, Media, Job


def seed():
    path = Path(settings.media_dir) / "seed.mp4"
    path.write_bytes(b"test-only-media")
    with SessionLocal() as db:
        media = Media(filename="seed.mp4", path=str(path), media_type="video", mime_type="video/mp4")
        db.add(media); db.flush()
        content = Content(media_id=media.id, transcript="Hello world", source_language="en")
        db.add(content); db.commit()
        return content.id


def test_auth_health_and_csrf(client, monkeypatch):
    assert client.get("/health", auth=None).status_code == 200
    assert client.get("/", auth=None).status_code == 401
    assert client.get("/", auth=("owner", "wrong")).status_code == 401
    assert client.get("/").status_code == 200
    assert client.post("/api/content", json={}, headers={"Origin": "https://evil.invalid"}).status_code == 403
    monkeypatch.setattr(settings, "auth_password", "")
    assert client.get("/api/content").status_code == 503


def test_content_validation_and_paths(client):
    assert client.post("/api/content", json={"media_id": 999}).status_code == 404
    item = client.post("/api/content", json={"title": "Draft"}).json()
    assert "voice_path" not in item and "rendered_media_path" not in item
    assert client.patch(f'/api/content/{item["id"]}', json={"title": None}).status_code == 422
    assert client.patch(f'/api/content/{item["id"]}', json={"title": "Edited"}).json()["title"] == "Edited"
    assert len(client.get("/api/content").json()) == 1
    assert client.get("/api/content/999").status_code == 404


@pytest.mark.parametrize("filename,mime", [("x.exe", "video/mp4"), ("x.mp4", "text/plain")])
def test_invalid_upload(client, filename, mime):
    assert client.post("/api/media", files={"file": (filename, b"invalid", mime)}).status_code == 400


def test_upload_probe_rejection_cleans_file(client, monkeypatch):
    before = set(main.MEDIA_ROOT.iterdir())
    def invalid(path):
        raise ValueError("Media is unreadable")
    monkeypatch.setattr(main, "probe", invalid)
    assert client.post("/api/media", files={"file": ("x.mp4", b"invalid", "video/mp4")}).status_code == 400
    assert set(main.MEDIA_ROOT.iterdir()) == before


def test_upload_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    assert client.post("/api/media", files={"file": ("x.mp4", b"a", "video/mp4")}).status_code == 413


def test_upload_contract(client, monkeypatch):
    # Contract test only. Real ffprobe acceptance is tested separately when installed.
    monkeypatch.setattr(main, "probe", lambda path: {"streams": [{"codec_type": "video"}], "format": {"duration": "2"}})
    result = client.post("/api/media", files={"file": ("../../x.mp4", b"fixture", "video/mp4")})
    assert result.status_code == 200
    assert result.json()["filename"] == "x.mp4"
    assert "path" not in client.get("/api/media").json()[0]
    assert client.get(f'/api/media/{result.json()["id"]}').content == b"fixture"


@pytest.mark.parametrize("captions", [
    [{"start_ms": -1, "end_ms": 1, "text": "x"}],
    [{"start_ms": 1, "end_ms": 1, "text": "x"}],
    [{"start_ms": 0, "end_ms": 10, "text": " "}],
    [{"start_ms": 0, "end_ms": 10, "text": "x"}, {"start_ms": 5, "end_ms": 20, "text": "y"}],
])
def test_caption_invalid_atomic(client, captions):
    cid = seed()
    url = f"/api/content/{cid}/captions"
    good = [{"start_ms": 1000, "end_ms": 1250, "text": "Hello"}]
    assert client.put(url, json={"captions": good}).status_code == 200
    assert client.put(url, json={"captions": captions}).status_code in {400, 422}
    assert client.get(url).json()[0]["start_ms"] == 1000


def test_missing_ai_is_actionable(client, monkeypatch):
    cid = seed()
    monkeypatch.setattr(settings, "whisper_binary", "/missing/whisper-cli")
    response = client.post(f"/api/content/{cid}/generate")
    assert response.status_code == 503
    assert "Whisper" in response.json()["detail"]
    assert "/missing" not in response.text
    assert client.post("/api/voice", json={"content_id": cid, "text": "hello", "voice_id": "nonexistent"}).status_code == 404


def test_transcript_survives_metadata_failure(client, monkeypatch):
    cid = seed()
    monkeypatch.setattr(main, "transcribe", lambda path: {"text": "A test", "language": "en", "words": [{"text": "test", "start_ms": 1200, "end_ms": 1600}]})
    def fail(*args):
        raise RuntimeError("Ollama unavailable; start the service")
    monkeypatch.setattr(main, "generate_metadata", fail)
    assert client.post(f"/api/content/{cid}/generate").status_code == 503
    assert client.get(f"/api/content/{cid}").json()["transcript"] == "A test"
    assert client.get(f"/api/content/{cid}/captions").json()[0]["start_ms"] == 1200


def test_schedule_validation_and_duplicate(client):
    cid = seed()
    data = {"content_id": cid, "platform": "youtube", "publish_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    assert client.post("/api/schedule", json={**data, "publish_at": "2030-01-01T12:00:00"}).status_code == 400
    assert client.post("/api/schedule", json=data).status_code == 200
    assert client.post("/api/schedule", json=data).status_code == 409


@pytest.mark.parametrize("status", ["PUBLISHED", "PUBLISHING", "REVIEW_REQUIRED", "QUEUED"])
def test_retry_cannot_duplicate(client, status):
    cid = seed()
    with SessionLocal() as db:
        job = Job(content_id=cid, platform="facebook", publish_at=datetime.utcnow(), status=status)
        db.add(job); db.commit(); jid = job.id
    assert client.post(f"/api/jobs/{jid}/retry").status_code == 409


def test_media_traversal(client):
    cid = seed()
    with SessionLocal() as db:
        content = db.get(Content, cid)
        content.rendered_media_path = "/etc/passwd"
        db.commit()
    assert client.get(f"/api/content/{cid}/rendered-media").status_code == 403


def test_render_preconditions_without_ffmpeg(client):
    cid = seed()
    assert client.post(f"/api/content/{cid}/render", json={"content_id": cid + 1}).status_code == 400
    response = client.post(f"/api/content/{cid}/render", json={"content_id": cid})
    assert response.status_code == 400 and "voice-over" in response.text


def test_reconcile_requires_verification(client):
    cid = seed()
    with SessionLocal() as db:
        job = Job(content_id=cid, platform="facebook", publish_at=datetime.utcnow(), status="REVIEW_REQUIRED", attempts=1)
        db.add(job); db.commit(); jid = job.id
    assert client.post(f"/api/jobs/{jid}/reconcile", json={"published": True, "note": "Checked platform history"}).status_code == 400
    response = client.post(f"/api/jobs/{jid}/reconcile", json={"published": False, "note": "Checked platform history: nothing published"})
    assert response.json()["status"] == "FAILED"
    assert client.post(f"/api/jobs/{jid}/retry").json()["status"] == "QUEUED"
    assert client.delete(f"/api/jobs/{jid}").status_code == 409


def test_scheduled_content_cannot_change(client):
    cid = seed()
    payload = {"content_id": cid, "platform": "youtube", "publish_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    assert client.post("/api/schedule", json=payload).status_code == 200
    assert client.patch(f"/api/content/{cid}", json={"title": "changed"}).status_code == 409


def test_voice_caption_audio_provenance(client, monkeypatch):
    cid = seed()
    with SessionLocal() as db:
        content = db.get(Content, cid)
        content.voice_path = str(main.MEDIA_ROOT / "voice.wav")
        Path(content.voice_path).write_bytes(b"test-only")
        db.commit()
    monkeypatch.setattr(main, "transcribe", lambda path: {"text": "spoken", "language": "en", "words": [{"start_ms": 0, "end_ms": 300, "text": "spoken"}]})
    assert client.post(f"/api/content/{cid}/voice-captions").status_code == 200
    assert client.get(f"/api/content/{cid}").json()["transcript"] == "Hello world"
    response = client.post(f"/api/content/{cid}/render", json={"content_id": cid, "use_voiceover": False, "burn_subtitles": True})
    assert response.status_code == 400
    assert "caption_audio_path" not in client.get(f"/api/content/{cid}").json()


def test_real_api_render_contract(client, video, ffmpeg, monkeypatch):
    # Real FFmpeg render; final ffprobe boundary is stubbed when unavailable.
    import shutil
    cid = seed()
    source = main.MEDIA_ROOT / "seed.mp4"
    shutil.copyfile(video, source)
    original = source.read_bytes()
    monkeypatch.setattr(main, "probe", lambda path: {"streams": [{"codec_type": "video"}]})
    url = f"/api/content/{cid}/render"
    payload = {"content_id": cid, "use_voiceover": False, "burn_subtitles": False}
    first = client.post(url, json=payload)
    assert first.status_code == 200
    assert "path" not in first.json()
    preview = client.get(first.json()["preview_url"])
    assert preview.status_code == 200 and preview.headers["content-type"] == "video/mp4"
    assert client.get(first.json()["preview_url"], headers={"Range": "bytes=0-9"}).status_code == 206
    assert client.post(url, json=payload).status_code == 200
    assert source.read_bytes() == original
    assert not list(main.MEDIA_ROOT.glob("render-*/"))
