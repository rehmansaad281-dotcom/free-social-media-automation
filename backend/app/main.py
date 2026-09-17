from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .config import settings
from .db import init_db, get_db
from .models import Media, Content, Job, Caption, PlatformAccount
from .schemas import (
    ContentCreate,
    ContentUpdate,
    ScheduleCreate,
    VoiceRequest,
    CaptionSaveRequest,
    RenderRequest,
)
from .scheduler import start_scheduler
from .ai.content import generate_metadata
from .ai.transcription import transcribe
from .ai.translation import translate_text
from .ai.tts import synthesize, list_voices
from .media import replace_audio, burn_subtitles, captions_to_srt
from .integrations.tiktok import creator_info


app = FastAPI(title=settings.app_name)

MEDIA_ROOT = Path(settings.media_dir).resolve()

Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
Path("./data").mkdir(exist_ok=True)
Path("./secrets").mkdir(exist_ok=True)


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


@app.on_event("startup")
def startup():
    init_db()
    start_scheduler()


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

    original_filename = file.filename or "upload"
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
            f"Failed to save uploaded media: {exc}",
        ) from exc

    finally:
        await file.close()

    media_type = (
        "video"
        if file.content_type.startswith("video/")
        else "image"
    )

    item = Media(
        filename=original_filename,
        path=str(path),
        media_type=media_type,
        mime_type=file.content_type,
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return {
        "id": item.id,
        "filename": item.filename,
        "media_type": item.media_type,
        "mime_type": item.mime_type,
    }


@app.get("/api/media")
def list_media(db: Session = Depends(get_db)):
    return (
        db.query(Media)
        .order_by(Media.id.desc())
        .all()
    )


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

    return item


@app.get("/api/content")
def list_content(db: Session = Depends(get_db)):
    return (
        db.query(Content)
        .order_by(Content.id.desc())
        .all()
    )


@app.patch("/api/content/{content_id}")
def update_content(
    content_id: int,
    payload: ContentUpdate,
    db: Session = Depends(get_db),
):
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

    for key, value in updates.items():
        setattr(item, key, value)

    db.commit()
    db.refresh(item)

    return item


@app.post("/api/content/{content_id}/generate")
def generate(
    content_id: int,
    platform: str = "general",
    db: Session = Depends(get_db),
):
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

    generated = generate_metadata(
        result["text"],
        platform,
    )

    content.transcript = result["text"]
    content.source_language = result["language"]
    content.title = generated["title"]
    content.description = generated["description"]
    content.hashtags = generated["hashtags"]
    content.keywords = generated["keywords"]

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
                end_ms=max(
                    end_ms,
                    start_ms + 50,
                ),
                text=word["text"].strip(),
            )
        )

    db.commit()

    return {
        "language": result["language"],
        "transcript": result["text"],
        "words": result["words"],
        **generated,
    }


@app.post("/api/content/{content_id}/translate")
def translate(
    content_id: int,
    target: str = "en",
    db: Session = Depends(get_db),
):
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

    source = (
        content.source_language
        or "en"
    )

    translated = translate_text(
        content.transcript,
        source,
        target,
    )

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
    return list_voices()


@app.post("/api/voice")
def voice(
    payload: VoiceRequest,
    db: Session = Depends(get_db),
):
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

    synthesize(
        payload.text,
        str(output),
        model,
    )

    content.voice_path = str(output)
    content.voice_id = (
        payload.voice_id
        or Path(model).stem
    )

    db.commit()

    return {
        "path": str(output),
        "voice_id": content.voice_id,
    }


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
    if not db.get(
        Content,
        content_id,
    ):
        raise HTTPException(
            404,
            "Content not found",
        )

    for caption in payload.captions:
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

    if payload.use_voiceover:
        if media.media_type != "video":
            raise HTTPException(
                400,
                "Voice-over rendering currently requires video media",
            )

        if not content.voice_path:
            raise HTTPException(
                400,
                "Generate voice-over first",
            )

        voice_path = _safe_media_path(
            content.voice_path
        )

        if not voice_path.is_file():
            raise HTTPException(
                404,
                "Voice-over file not found",
            )

        output = (
            MEDIA_ROOT
            / f"render_{content.id}_audio.mp4"
        )

        replace_audio(
            str(current),
            str(voice_path),
            str(output),
        )

        current = output

    if payload.burn_subtitles:
        captions = (
            db.query(Caption)
            .filter(
                Caption.content_id == content.id
            )
            .order_by(Caption.start_ms)
            .all()
        )

        if not captions:
            raise HTTPException(
                400,
                "No captions available",
            )

        srt = (
            MEDIA_ROOT
            / f"captions_{content.id}.srt"
        )

        captions_to_srt(
            captions,
            str(srt),
        )

        output = (
            MEDIA_ROOT
            / f"render_{content.id}_final.mp4"
        )

        burn_subtitles(
            str(current),
            str(srt),
            str(output),
            payload.subtitle_font_size,
        )

        current = output

    if not current.is_file():
        raise HTTPException(
            500,
            "Rendered media file was not created",
        )

    content.rendered_media_path = str(
        current
    )

    content.status = "READY"

    db.commit()

    return {
        "path": str(current),
        "status": content.status,
        "preview_url": (
            f"/api/content/{content.id}/rendered-media"
        ),
    }


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

    content = db.get(
        Content,
        payload.content_id,
    )

    if not content:
        raise HTTPException(
            404,
            "Content not found",
        )

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

    job = Job(
        content_id=payload.content_id,
        platform=payload.platform,
        publish_at=publish_at,
        max_attempts=payload.max_attempts,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


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

    job.status = "QUEUED"
    job.error = ""
    job.retry_at = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    db.commit()

    return job


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
