from pathlib import Path
from contextlib import asynccontextmanager
import secrets
import subprocess
import tempfile
import shutil
from urllib.parse import urlsplit
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from .errors import public_error
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from .config import settings
from .db import init_db, get_db
from .models import Media, Content, Job, Caption, PlatformAccount, PublicationAttempt
from .schemas import (
    ContentCreate,
    ContentUpdate,
    ScheduleCreate,
    VoiceRequest,
    CaptionSaveRequest,
    RenderRequest,
    ReconcileRequest,
)
from .scheduler import start_scheduler, scheduler
from .ai.content import generate_metadata
from .ai.transcription import transcribe
from .ai.translation import translate_text
from .ai.tts import synthesize, list_voices
from .media import replace_audio, burn_subtitles, captions_to_srt, probe, normalize_video
from .integrations.tiktok import creator_info


security = HTTPBasic(auto_error=False)


def authenticate(credentials: HTTPBasicCredentials | None = Depends(security)):
    if not settings.auth_password:
        raise HTTPException(503, "Set AUTH_PASSWORD before using the application.")
    if not credentials or not (secrets.compare_digest(credentials.username.encode(), settings.auth_username.encode())
            and secrets.compare_digest(credentials.password.encode(), settings.auth_password.encode())):
        raise HTTPException(401, "Owner authentication required", headers={"WWW-Authenticate": "Basic"})


@asynccontextmanager
async def lifespan(app):
    init_db()
    if settings.scheduler_enabled:
        start_scheduler()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=True)


app = FastAPI(title=settings.app_name, lifespan=lifespan, dependencies=[Depends(authenticate)],
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def same_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and (request.headers.get("sec-fetch-site") == "cross-site" or (origin and urlsplit(origin).netloc != request.headers.get("host"))):
        return JSONResponse(status_code=403, content={"detail": "Cross-origin mutations are not allowed"})
    if request.url.path in {"/health", "/api/health"}:
        return JSONResponse({"status": "ok"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RuntimeError)
async def dependency_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": public_error(exc)})


@app.exception_handler(ValueError)
async def input_error(request, exc):
    return JSONResponse(status_code=400, content={"detail": public_error(exc)})


@app.exception_handler(subprocess.TimeoutExpired)
async def timeout_error(request, exc):
    return JSONResponse(status_code=504, content={"detail": "Local processing timed out. Check model size and PROCESS_TIMEOUT."})


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Operation failed unexpectedly. Check server configuration and service availability."})


def public_record(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns
            if column.name not in {"path", "voice_path", "rendered_media_path", "model_path", "caption_audio_path"}}


MEDIA_ROOT = Path(settings.media_dir).resolve()

Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
Path("./data").mkdir(exist_ok=True)
Path("./secrets").mkdir(exist_ok=True)


def require_editable(db: Session, content_id: int):
    if db.query(Job).filter(Job.content_id == content_id, Job.status.in_(["QUEUED", "PUBLISHING", "REVIEW_REQUIRED"])).first():
        raise HTTPException(409, "Content is queued or publishing. Cancel the unattempted queue job or reconcile its outcome before editing.")


def _safe_media_path(path: str) -> Path:
    """
    Resolve a stored media path and make sure it remains inside
    the configured media directory.
    """
    candidate = Path(path).resolve()

    try:
        candidate.relative_to(MEDIA_ROOT)
    except ValueError as exc:
        raise HTTPException(
            403,
            "Media path is outside the configured media directory",
        ) from exc

    return candidate


def _utc_naive(value: datetime) -> datetime:
    """
    Convert an incoming datetime to UTC and store it as a naive UTC
    datetime because the current SQLAlchemy model uses DateTime without
    timezone=True.
    """
    if value.tzinfo is None:
        return value

    return value.astimezone(timezone.utc).replace(tzinfo=None)


@app.get("/")
def home():
    return FileResponse("frontend/index.html")


@app.get("/health")
def root_health():
    return {
        "status": "ok",
        "mode": "private-free-first",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/health")
def api_health():
    return {
        "status": "ok",
        "mode": "private-free-first",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/media")
async def upload_media(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.content_type or not (
        file.content_type.startswith("video/")
        or file.content_type.startswith("image/")
    ):
        raise HTTPException(
            400,
            "Only video/image files are allowed",
        )

    original_filename = Path((file.filename or "upload").replace("\\", "/")).name
    ext = Path(original_filename).suffix.lower()

    allowed_extensions = {
        ".mp4",
        ".mov",
        ".m4v",
        ".avi",
        ".mkv",
        ".webm",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
    }

    if ext not in allowed_extensions:
        raise HTTPException(
            400,
            "Unsupported media file extension",
        )

    name = f"{uuid4().hex}{ext}"
    path = MEDIA_ROOT / name

    max_bytes = settings.max_upload_mb * 1024 * 1024
    total_bytes = 0

    try:
        with path.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total_bytes += len(chunk)

                if total_bytes > max_bytes:
                    raise HTTPException(
                        413,
                        "File exceeds configured upload limit",
                    )

                output.write(chunk)

    except HTTPException:
        path.unlink(missing_ok=True)
        raise

    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(
            500,
            "Failed to save uploaded media. Check storage space and directory permissions.",
        ) from exc

    finally:
        await file.close()

    media_type = (
        "video"
        if file.content_type.startswith("video/")
        else "image"
    )

    try:
        info = probe(str(path))
        streams = [stream for stream in info["streams"] if stream.get("codec_type") == "video"]
        image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        expected_type = "image" if ext in image_exts else "video"
        if not streams or expected_type != media_type:
            raise ValueError("File extension, MIME type, and readable media must agree.")
        image_codecs = {".jpg": "mjpeg", ".jpeg": "mjpeg", ".png": "png", ".webp": "webp", ".gif": "gif"}
        if ext in image_codecs and streams[0].get("codec_name") != image_codecs[ext]:
            raise ValueError("Image content does not match its extension.")
        if media_type == "video" and float(info.get("format", {}).get("duration", 0)) <= 0:
            raise ValueError("Video must have a positive duration.")
    except Exception:
        path.unlink(missing_ok=True)
        raise

    item = Media(
        filename=original_filename,
        path=str(path),
        media_type=media_type,
        mime_type=file.content_type,
    )

    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise

    return {
        "id": item.id,
        "filename": item.filename,
        "media_type": item.media_type,
        "mime_type": item.mime_type,
    }


@app.get("/api/media")
def list_media(db: Session = Depends(get_db)):
    return [public_record(item) for item in db.query(Media).order_by(Media.id.desc()).all()]


@app.get("/api/media/{media_id}")
def get_media(
    media_id: int,
    db: Session = Depends(get_db),
):
    item = db.get(Media, media_id)

    if not item:
        raise HTTPException(
            404,
            "Media not found",
        )

    path = _safe_media_path(item.path)

    if not path.is_file():
        raise HTTPException(
            404,
            "Media file not found",
        )

    return FileResponse(
        path,
        media_type=item.mime_type or None,
        filename=item.filename,
    )


@app.post("/api/content")
def create_content(
    payload: ContentCreate,
    db: Session = Depends(get_db),
):
    if payload.media_id is not None:
        media = db.get(Media, payload.media_id)

        if not media:
            raise HTTPException(
                404,
                "Media not found",
            )

    item = Content(
        **payload.model_dump()
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return public_record(item)


@app.get("/api/content")
def list_content(db: Session = Depends(get_db)):
    return [public_record(item) for item in db.query(Content).order_by(Content.id.desc()).all()]


@app.get("/api/content/{content_id}")
def get_content(content_id: int, db: Session = Depends(get_db)):
    item = db.get(Content, content_id)
    if not item:
        raise HTTPException(404, "Content not found")
    return public_record(item)


@app.patch("/api/content/{content_id}")
def update_content(
    content_id: int,
    payload: ContentUpdate,
    db: Session = Depends(get_db),
):
    require_editable(db, content_id)
    item = db.get(Content, content_id)

    if not item:
        raise HTTPException(
            404,
            "Content not found",
        )

    updates = payload.model_dump(
        exclude_unset=True
    )

    if "media_id" in updates and updates["media_id"] is not None:
        media = db.get(
            Media,
            updates["media_id"],
        )

        if not media:
            raise HTTPException(
                404,
                "Media not found",
            )

    if any(value is None for key, value in updates.items() if key != "media_id"):
        raise HTTPException(422, "Content text fields cannot be null")
    if "media_id" in updates and updates["media_id"] != item.media_id:
        item.transcript = item.translated_text = item.voice_path = item.rendered_media_path = ""
        item.source_language = item.caption_audio_path = ""
        db.query(Caption).filter(Caption.content_id == item.id).delete()
    for key, value in updates.items():
        setattr(item, key, value)

    db.commit()
    db.refresh(item)

    return public_record(item)


@app.post("/api/content/{content_id}/generate")
def generate(
    content_id: int,
    platform: str = "general",
    metadata: bool = True,
    db: Session = Depends(get_db),
):
    require_editable(db, content_id)
    content = db.get(
        Content,
        content_id,
    )

    if not content or not content.media_id:
        raise HTTPException(
            404,
            "Content/media not found",
        )

    media = db.get(
        Media,
        content.media_id,
    )

    if not media:
        raise HTTPException(
            404,
            "Media not found",
        )

    if media.media_type != "video":
        raise HTTPException(
            400,
            "AI transcription requires a video",
        )

    media_path = _safe_media_path(
        media.path
    )

    if not media_path.is_file():
        raise HTTPException(
            404,
            "Media file not found",
        )

    result = transcribe(
        str(media_path)
    )

    content.transcript = result["text"]
    content.source_language = result["language"]
    content.caption_audio_path = str(media_path)
    content.translated_text = content.voice_path = content.rendered_media_path = ""

    db.query(Caption).filter(
        Caption.content_id == content.id
    ).delete()

    for word in result["words"]:
        start_ms = int(word["start_ms"])
        end_ms = int(word["end_ms"])

        db.add(
            Caption(
                content_id=content.id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=word["text"].strip(),
            )
        )

    db.commit()
    if not metadata:
        return result
    generated = generate_metadata(result["text"], platform)
    for key, value in generated.items():
        setattr(content, key, value)
    db.commit()

    return {
        "language": result["language"],
        "transcript": result["text"],
        "words": result["words"],
        **generated,
    }


@app.post("/api/content/{content_id}/voice-captions")
def voice_captions(content_id: int, db: Session = Depends(get_db)):
    require_editable(db, content_id)
    content = db.get(Content, content_id)
    if not content or not content.voice_path:
        raise HTTPException(400, "Generate voice-over first")
    result = transcribe(str(_safe_media_path(content.voice_path)))
    db.query(Caption).filter(Caption.content_id == content_id).delete()
    for word in result["words"]:
        db.add(Caption(content_id=content_id, **word))
    content.caption_audio_path = content.voice_path
    content.rendered_media_path = ""
    db.commit()
    return result


@app.post("/api/content/{content_id}/metadata")
def metadata(content_id: int, platform: str = "general", db: Session = Depends(get_db)):
    require_editable(db, content_id)
    content = db.get(Content, content_id)
    if not content:
        raise HTTPException(404, "Content not found")
    generated = generate_metadata(content.transcript, platform)
    for key, value in generated.items():
        setattr(content, key, value)
    db.commit()
    return generated


@app.post("/api/content/{content_id}/translate")
def translate(
    content_id: int,
    target: str = "en",
    db: Session = Depends(get_db),
):
    require_editable(db, content_id)
    content = db.get(
        Content,
        content_id,
    )

    if not content or not content.transcript:
        raise HTTPException(
            400,
            "Generate transcript first",
        )

    target = target.strip()

    if not target:
        raise HTTPException(
            400,
            "Target language is required",
        )

    source = content.source_language
    if not source:
        raise HTTPException(400, "Source language is unknown. Regenerate transcription with language detection.")

    translated = translate_text(
        content.transcript,
        source,
        target,
    )

    content.voice_path = content.rendered_media_path = ""
    content.target_language = target
    content.translated_text = translated

    db.commit()

    return {
        "source": source,
        "target": target,
        "translated_text": translated,
    }


@app.get("/api/voices")
def voices():
    return [{k: v for k, v in voice.items() if k != "model_path"} for voice in list_voices()]


@app.post("/api/voice")
def voice(
    payload: VoiceRequest,
    db: Session = Depends(get_db),
):
    require_editable(db, payload.content_id)
    content = db.get(
        Content,
        payload.content_id,
    )

    if not content:
        raise HTTPException(
            404,
            "Content not found",
        )

    if not payload.text.strip():
        raise HTTPException(
            400,
            "Text is required for voice generation",
        )

    voice_map = {
        voice["voice_id"]: voice
        for voice in list_voices()
    }

    chosen = voice_map.get(
        payload.voice_id or ""
    )

    if payload.voice_id and not chosen:
        raise HTTPException(
            404,
            "Voice not found",
        )

    model = (
        chosen["model_path"]
        if chosen
        else settings.piper_model
    )

    output = (
        MEDIA_ROOT
        / f"voice_{content.id}_{uuid4().hex[:8]}.wav"
    )

    try:
        synthesize(payload.text, str(output), model)
    except Exception:
        output.unlink(missing_ok=True)
        raise

    content.rendered_media_path = ""
    content.voice_path = str(output)
    content.voice_id = (
        payload.voice_id
        or Path(model).stem
    )

    db.commit()

    return {
        "audio_url": f"/api/content/{content.id}/voice",
        "voice_id": content.voice_id,
    }


@app.get("/api/content/{content_id}/voice")
def voice_audio(content_id: int, db: Session = Depends(get_db)):
    content = db.get(Content, content_id)
    if not content or not content.voice_path:
        raise HTTPException(404, "Voice audio not available")
    path = _safe_media_path(content.voice_path)
    if not path.is_file():
        raise HTTPException(404, "Voice audio file not found")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/content/{content_id}/captions")
def get_captions(
    content_id: int,
    db: Session = Depends(get_db),
):
    if not db.get(
        Content,
        content_id,
    ):
        raise HTTPException(
            404,
            "Content not found",
        )

    return (
        db.query(Caption)
        .filter(
            Caption.content_id == content_id
        )
        .order_by(Caption.start_ms)
        .all()
    )


@app.put("/api/content/{content_id}/captions")
def save_captions(
    content_id: int,
    payload: CaptionSaveRequest,
    db: Session = Depends(get_db),
):
    require_editable(db, content_id)
    if not db.get(
        Content,
        content_id,
    ):
        raise HTTPException(
            404,
            "Content not found",
        )

    db.get(Content, content_id).rendered_media_path = ""
    previous_end = 0
    for caption in sorted(payload.captions, key=lambda c: c.start_ms):
        if not caption.text.strip() or caption.start_ms < previous_end:
            raise HTTPException(400, "Captions require text and must not overlap or duplicate")
        previous_end = caption.end_ms
        if caption.end_ms <= caption.start_ms:
            raise HTTPException(
                400,
                "Caption end time must be greater than start time",
            )

    db.query(Caption).filter(
        Caption.content_id == content_id
    ).delete()

    for caption in payload.captions:
        db.add(
            Caption(
                content_id=content_id,
                **caption.model_dump(),
            )
        )

    db.commit()

    return {
        "saved": len(
            payload.captions
        )
    }


@app.post("/api/content/{content_id}/render")
def render_content(
    content_id: int,
    payload: RenderRequest,
    db: Session = Depends(get_db),
):
    require_editable(db, content_id)
    content = db.get(
        Content,
        content_id,
    )

    if not content or not content.media_id:
        raise HTTPException(
            404,
            "Content/media not found",
        )

    media = db.get(
        Media,
        content.media_id,
    )

    if not media:
        raise HTTPException(
            404,
            "Media not found",
        )

    current = _safe_media_path(
        media.path
    )

    if not current.is_file():
        raise HTTPException(
            404,
            "Original media file not found",
        )

    if payload.content_id != content_id:
        raise HTTPException(400, "URL and request Content IDs must match")
    if media.media_type != "video":
        raise HTTPException(400, "Final video rendering requires video media")
    if payload.use_voiceover and not content.voice_path:
        raise HTTPException(400, "Generate voice-over first")
    if payload.burn_subtitles:
        expected_audio = content.voice_path if payload.use_voiceover else media.path
        if (content.caption_audio_path and content.caption_audio_path != expected_audio) or (payload.use_voiceover and not content.caption_audio_path):
            raise HTTPException(400, "Generate captions from the selected audio before rendering")
    output = MEDIA_ROOT / f"render_{content.id}_{uuid4().hex}.mp4"
    try:
        with tempfile.TemporaryDirectory(prefix="render-", dir=MEDIA_ROOT) as temp:
            temp = Path(temp)
            normalized = temp / "normalized.mp4"
            normalize_video(str(current), str(normalized))
            current = normalized
            if payload.use_voiceover:
                if not content.voice_path:
                    raise HTTPException(400, "Generate voice-over first")
                voice_path = _safe_media_path(content.voice_path)
                if not voice_path.is_file():
                    raise HTTPException(404, "Voice-over file not found")
                current = Path(replace_audio(str(current), str(voice_path), str(temp / "audio.mp4")))
            if payload.burn_subtitles:
                expected_audio = content.voice_path if payload.use_voiceover else media.path
                if content.caption_audio_path and content.caption_audio_path != expected_audio:
                    raise HTTPException(400, "Caption timings belong to different audio. Generate captions from the selected audio before rendering.")
                if payload.use_voiceover and not content.caption_audio_path:
                    raise HTTPException(400, "Generate voice-over captions before burning subtitles with voice-over.")
                captions = db.query(Caption).filter(Caption.content_id == content.id).order_by(Caption.start_ms).all()
                if not captions:
                    raise HTTPException(400, "No captions available")
                srt = captions_to_srt(captions, str(temp / "captions.srt"))
                current = Path(burn_subtitles(str(current), srt, str(temp / "final.mp4"), payload.subtitle_font_size))
            probe(str(current))
            shutil.move(str(current), output)
        content.rendered_media_path = str(output)
        content.status = "READY"
        db.commit()
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {"status": content.status, "preview_url": f"/api/content/{content.id}/rendered-media"}


@app.get("/api/content/{content_id}/rendered-media")
def get_rendered_media(
    content_id: int,
    db: Session = Depends(get_db),
):
    content = db.get(
        Content,
        content_id,
    )

    if not content:
        raise HTTPException(
            404,
            "Content not found",
        )

    if not content.rendered_media_path:
        raise HTTPException(
            404,
            "Rendered media not available",
        )

    path = _safe_media_path(
        content.rendered_media_path
    )

    if not path.is_file():
        raise HTTPException(
            404,
            "Rendered media file not found",
        )

    return FileResponse(
        path,
        media_type="video/mp4",
        filename=path.name,
    )


@app.post("/api/schedule")
def schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
):
    if payload.platform not in {
        "facebook",
        "youtube",
        "tiktok",
    }:
        raise HTTPException(
            400,
            "Unsupported platform",
        )

    if settings.database_url.startswith("sqlite"):
        db.execute(text("BEGIN IMMEDIATE"))
    content = db.get(Content, payload.content_id)
    if not content:
        raise HTTPException(404, "Content not found")

    media = db.get(Media, content.media_id) if content.media_id else None
    if not media:
        raise HTTPException(400, "Attach media before scheduling")
    if payload.platform in {"youtube", "tiktok"} and media.media_type != "video":
        raise HTTPException(400, "This platform requires video")
    if db.query(Job).filter(Job.content_id == content.id, Job.platform == payload.platform,
                            Job.status.in_(["QUEUED", "PUBLISHING", "PUBLISHED", "UPLOADED", "REVIEW_REQUIRED"])).first():
        raise HTTPException(409, "Content already has an active or published job for this platform")
    if payload.publish_at.tzinfo is None:
        raise HTTPException(400, "Schedule time must include a timezone offset")
    publish_at = _utc_naive(
        payload.publish_at
    )

    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    if publish_at <= now:
        raise HTTPException(
            400,
            "Schedule time must be in the future",
        )

    if payload.platform == "tiktok":
        if not payload.consent or not payload.privacy_level:
            raise HTTPException(400, "TikTok requires explicit privacy selection and publishing consent")
        info = creator_info()
        if payload.privacy_level not in info.get("privacy_level_options", []):
            raise HTTPException(400, "Selected TikTok privacy is not available for this creator")
    job = Job(
        privacy_level=payload.privacy_level or "",
        content_id=payload.content_id,
        platform=payload.platform,
        publish_at=publish_at,
        max_attempts=payload.max_attempts,
    )

    db.add(job)
    db.commit()
    db.refresh(job)
    return public_record(job)


@app.get("/api/jobs")
def jobs(
    db: Session = Depends(get_db),
):
    return (
        db.query(Job)
        .order_by(Job.id.desc())
        .all()
    )


@app.post("/api/jobs/{job_id}/retry")
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = db.get(
        Job,
        job_id,
    )

    if not job:
        raise HTTPException(
            404,
            "Job not found",
        )

    if job.status != "FAILED" or job.external_id:
        raise HTTPException(409, "Only confirmed failed jobs without an external ID can be retried")
    job.max_attempts = max(job.max_attempts, job.attempts + 1)
    job.status = "QUEUED"
    job.error = ""
    job.retry_at = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    db.commit()

    db.refresh(job)
    return public_record(job)


@app.get("/api/jobs/{job_id}/attempts")
def attempts(job_id: int, db: Session = Depends(get_db)):
    if not db.get(Job, job_id):
        raise HTTPException(404, "Job not found")
    return db.query(PublicationAttempt).filter(PublicationAttempt.job_id == job_id).order_by(PublicationAttempt.id).all()


@app.post("/api/jobs/{job_id}/reconcile")
def reconcile(job_id: int, payload: ReconcileRequest, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "REVIEW_REQUIRED":
        raise HTTPException(409, "Only uncertain publication outcomes can be reconciled")
    if payload.published and not payload.external_id.strip():
        raise HTTPException(400, "Provide the verified platform post/video ID")
    job.status = "PUBLISHED" if payload.published else "FAILED"
    job.external_id = payload.external_id.strip() if payload.published else ""
    job.error = "Owner reconciled: " + public_error(payload.note)
    attempt = db.query(PublicationAttempt).filter(PublicationAttempt.job_id == job.id).order_by(PublicationAttempt.id.desc()).first()
    if attempt:
        attempt.status, attempt.external_id, attempt.error = job.status, job.external_id, job.error
        attempt.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if payload.published:
        content = db.get(Content, job.content_id)
        if content:
            content.status = "PUBLISHED"
    db.commit()
    db.refresh(job)
    return public_record(job)


@app.delete("/api/jobs/{job_id}")
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = db.get(
        Job,
        job_id,
    )

    if not job:
        raise HTTPException(
            404,
            "Job not found",
        )

    if job.status != "QUEUED" or job.attempts:
        raise HTTPException(409, "Only unattempted queued jobs can be deleted; history is retained")
    db.delete(job)
    db.commit()

    return {
        "deleted": job_id
    }


@app.get("/api/accounts")
def accounts(
    db: Session = Depends(get_db),
):
    return (
        db.query(PlatformAccount)
        .order_by(PlatformAccount.id)
        .all()
    )


@app.get("/api/tiktok/creator")
def tiktok_creator():
    if not settings.tiktok_access_token:
        raise HTTPException(
            400,
            "TikTok access token not configured",
        )

    return creator_info()
