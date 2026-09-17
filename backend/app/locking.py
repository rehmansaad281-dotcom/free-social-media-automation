"""Cross-process locks for this single-host, SQLite deployment."""
from functools import wraps
from inspect import signature
from pathlib import Path
from filelock import FileLock, Timeout
from fastapi import HTTPException
from .config import settings


def content_locked(function):
    sig = signature(function)

    @wraps(function)
    def locked(*args, **kwargs):
        values = sig.bind(*args, **kwargs).arguments
        payload = values.get("payload")
        content_id = values.get("content_id") or getattr(payload, "content_id", None)
        if not content_id and values.get("job_id") and values.get("db"):
            from .models import Job
            job = values["db"].get(Job, values["job_id"])
            content_id = job.content_id if job else None
        if not content_id:
            return function(*args, **kwargs)
        root = Path(settings.lock_dir)
        root.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(root / f"content-{int(content_id)}.lock"))
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise HTTPException(409, "This content is being modified. Wait for its current operation to finish.") from exc
        try:
            return function(*args, **kwargs)
        finally:
            lock.release()
    return locked
