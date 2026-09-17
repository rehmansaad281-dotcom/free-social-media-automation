"""Persistent local AI/render work; publishing retains its separate job queue."""
import json
from contextvars import ContextVar
current_task_id = ContextVar("current_media_task", default=None)
from datetime import datetime
from sqlalchemy import update
from .db import SessionLocal
from .models import MediaTask
from .errors import public_error
from .schemas import VoiceRequest, RenderRequest


def recover_media_tasks():
    # Called only after the process-wide runtime lock has been acquired.
    with SessionLocal() as db:
        db.query(MediaTask).filter_by(status="RUNNING").update({"status": "FAILED",
            "error": "Application stopped during local processing. Retry the task; original media is preserved.",
            "finished_at": datetime.utcnow()})
        db.commit()


def execute_media_tasks():
    from . import main
    with SessionLocal() as db:
        ids = [row.id for row in db.query(MediaTask).filter_by(status="QUEUED").order_by(MediaTask.id).all()]
    for task_id in ids:
        with SessionLocal() as db:
            claimed = db.execute(update(MediaTask).where(MediaTask.id == task_id, MediaTask.status == "QUEUED").values(status="RUNNING"))
            db.commit()
            if not claimed.rowcount:
                continue
            task = db.get(MediaTask, task_id)
            context = current_task_id.set(task_id)
            try:
                options = json.loads(task.payload)
                cid = task.content_id
                if task.action == "generate":
                    result = main.generate(cid, platform=options.get("platform", "general"), metadata=options.get("metadata", True), db=db)
                elif task.action == "metadata":
                    result = main.metadata(cid, platform=options.get("platform", "general"), db=db)
                elif task.action == "translate":
                    result = main.translate(cid, target=options.get("target", "en"), db=db)
                elif task.action == "voice":
                    result = main.voice(VoiceRequest(**options, content_id=cid), db=db)
                elif task.action == "voice-captions":
                    result = main.voice_captions(cid, db=db)
                elif task.action == "render":
                    result = main.render_content(cid, RenderRequest(**options, content_id=cid), db=db)
                else:
                    raise ValueError("Unsupported media task")
                task.status, task.result, task.error = "SUCCEEDED", json.dumps(result), ""
            except Exception as exc:
                db.rollback()
                task = db.get(MediaTask, task_id)
                task.status = "FAILED"
                task.error = public_error(getattr(exc, "detail", str(exc)))
            current_task_id.reset(context)
            task.finished_at = datetime.utcnow()
            db.commit()
