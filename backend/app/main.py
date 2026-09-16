from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from .config import settings
from .db import init_db, get_db
from .models import Media, Content, Job, Caption, PlatformAccount
from .schemas import ContentCreate, ContentUpdate, ScheduleCreate, VoiceRequest, CaptionSaveRequest, RenderRequest
from .scheduler import start_scheduler
from .ai.content import generate_metadata
from .ai.transcription import transcribe
from .ai.translation import translate_text
from .ai.tts import synthesize, list_voices
from .media import replace_audio, burn_subtitles, captions_to_srt
from .integrations.tiktok import creator_info

app = FastAPI(title=settings.app_name)
Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
Path("./data").mkdir(exist_ok=True)
Path("./secrets").mkdir(exist_ok=True)

@app.on_event("startup")
def startup():
    init_db(); start_scheduler()

@app.get("/")
def home(): return FileResponse("frontend/index.html")

@app.get("/api/health")
def health(): return {"status": "ok", "mode": "private-free-first", "time": datetime.now(timezone.utc).isoformat()}

@app.post("/api/media")
async def upload_media(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.content_type or not (file.content_type.startswith("video/") or file.content_type.startswith("image/")):
        raise HTTPException(400, "Only video/image files are allowed")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes: raise HTTPException(413, "File exceeds configured upload limit")
    ext = Path(file.filename or "").suffix.lower()
    name = f"{uuid4().hex}{ext}"; path = Path(settings.media_dir) / name; path.write_bytes(data)
    media_type = "video" if file.content_type.startswith("video/") else "image"
    item = Media(filename=file.filename or name, path=str(path), media_type=media_type, mime_type=file.content_type)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "filename": item.filename, "media_type": item.media_type, "mime_type": item.mime_type}

@app.get("/api/media")
def list_media(db: Session = Depends(get_db)): return db.query(Media).order_by(Media.id.desc()).all()

@app.get("/api/media/{media_id}")
def get_media(media_id: int, db: Session = Depends(get_db)):
    item = db.get(Media, media_id)
    if not item: raise HTTPException(404, "Media not found")
    return FileResponse(item.path, media_type=item.mime_type or None)

@app.post("/api/content")
def create_content(payload: ContentCreate, db: Session = Depends(get_db)):
    item = Content(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return item

@app.get("/api/content")
def list_content(db: Session = Depends(get_db)): return db.query(Content).order_by(Content.id.desc()).all()

@app.patch("/api/content/{content_id}")
def update_content(content_id: int, payload: ContentUpdate, db: Session = Depends(get_db)):
    item = db.get(Content, content_id)
    if not item: raise HTTPException(404, "Content not found")
    for k, v in payload.model_dump(exclude_unset=True).items(): setattr(item, k, v)
    db.commit(); db.refresh(item); return item

@app.post("/api/content/{content_id}/generate")
def generate(content_id: int, platform: str = "general", db: Session = Depends(get_db)):
    content = db.get(Content, content_id)
    if not content or not content.media_id: raise HTTPException(404, "Content/media not found")
    media = db.get(Media, content.media_id)
    if media.media_type != "video": raise HTTPException(400, "AI transcription requires a video")
    result = transcribe(media.path); generated = generate_metadata(result["text"], platform)
    content.transcript = result["text"]; content.source_language = result["language"]
    content.title, content.description = generated["title"], generated["description"]
    content.hashtags, content.keywords = generated["hashtags"], generated["keywords"]
    db.query(Caption).filter(Caption.content_id == content.id).delete()
    for w in result["words"]:
        db.add(Caption(content_id=content.id, start_ms=int(w["start"]*1000), end_ms=max(int(w["end"]*1000), int(w["start"]*1000)+50), text=w["word"].strip()))
    db.commit()
    return {"language": result["language"], "transcript": result["text"], "words": result["words"], **generated}

@app.post("/api/content/{content_id}/translate")
def translate(content_id: int, target: str = "en", db: Session = Depends(get_db)):
    content = db.get(Content, content_id)
    if not content or not content.transcript: raise HTTPException(400, "Generate transcript first")
    source = content.source_language or "en"; translated = translate_text(content.transcript, source, target)
    content.target_language, content.translated_text = target, translated; db.commit()
    return {"source": source, "target": target, "translated_text": translated}

@app.get("/api/voices")
def voices(): return list_voices()

@app.post("/api/voice")
def voice(payload: VoiceRequest, db: Session = Depends(get_db)):
    content = db.get(Content, payload.content_id)
    if not content: raise HTTPException(404, "Content not found")
    voice_map = {v["voice_id"]: v for v in list_voices()}; chosen = voice_map.get(payload.voice_id or "")
    model = chosen["model_path"] if chosen else settings.piper_model
    output = Path(settings.media_dir) / f"voice_{content.id}_{uuid4().hex[:8]}.wav"
    synthesize(payload.text, str(output), model); content.voice_path = str(output); content.voice_id = payload.voice_id or Path(model).stem; db.commit()
    return {"path": str(output), "voice_id": content.voice_id}

@app.get("/api/content/{content_id}/captions")
def get_captions(content_id: int, db: Session = Depends(get_db)):
    return db.query(Caption).filter(Caption.content_id == content_id).order_by(Caption.start_ms).all()

@app.put("/api/content/{content_id}/captions")
def save_captions(content_id: int, payload: CaptionSaveRequest, db: Session = Depends(get_db)):
    if not db.get(Content, content_id): raise HTTPException(404, "Content not found")
    db.query(Caption).filter(Caption.content_id == content_id).delete()
    for c in payload.captions: db.add(Caption(content_id=content_id, **c.model_dump()))
    db.commit(); return {"saved": len(payload.captions)}

@app.post("/api/content/{content_id}/render")
def render_content(content_id: int, payload: RenderRequest, db: Session = Depends(get_db)):
    content = db.get(Content, content_id)
    if not content or not content.media_id: raise HTTPException(404, "Content/media not found")
    media = db.get(Media, content.media_id); current = media.path
    if payload.use_voiceover:
        if not content.voice_path: raise HTTPException(400, "Generate voice-over first")
        out = Path(settings.media_dir) / f"render_{content.id}_audio.mp4"; replace_audio(current, content.voice_path, str(out)); current = str(out)
    if payload.burn_subtitles:
        captions = db.query(Caption).filter(Caption.content_id == content.id).order_by(Caption.start_ms).all()
        if not captions: raise HTTPException(400, "No captions available")
        srt = Path(settings.media_dir) / f"captions_{content.id}.srt"; captions_to_srt(captions, str(srt))
        out = Path(settings.media_dir) / f"render_{content.id}_final.mp4"; burn_subtitles(current, str(srt), str(out), payload.subtitle_font_size); current = str(out)
    content.rendered_media_path = current; content.status = "READY"; db.commit()
    return {"path": current, "status": content.status}

@app.post("/api/schedule")
def schedule(payload: ScheduleCreate, db: Session = Depends(get_db)):
    if payload.platform not in {"facebook", "youtube", "tiktok"}: raise HTTPException(400, "Unsupported platform")
    if not db.get(Content, payload.content_id): raise HTTPException(404, "Content not found")
    dt = payload.publish_at.replace(tzinfo=None)
    if dt <= datetime.utcnow(): raise HTTPException(400, "Schedule time must be in the future")
    job = Job(content_id=payload.content_id, platform=payload.platform, publish_at=dt, max_attempts=payload.max_attempts)
    db.add(job); db.commit(); db.refresh(job); return job

@app.get("/api/jobs")
def jobs(db: Session = Depends(get_db)): return db.query(Job).order_by(Job.id.desc()).all()

@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    job.status, job.error, job.publish_at = "QUEUED", "", datetime.utcnow(); db.commit(); return job

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    db.delete(job); db.commit(); return {"deleted": job_id}

@app.get("/api/accounts")
def accounts(db: Session = Depends(get_db)): return db.query(PlatformAccount).order_by(PlatformAccount.id).all()

@app.get("/api/tiktok/creator")
def tiktok_creator():
    if not settings.tiktok_access_token: raise HTTPException(400, "TikTok access token not configured")
    return creator_info()
