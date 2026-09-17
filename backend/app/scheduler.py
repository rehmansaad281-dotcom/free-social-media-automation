from datetime import datetime, timezone, timedelta
from pathlib import Path
from .config import settings
from .errors import public_error
from sqlalchemy import update

from apscheduler.schedulers.background import BackgroundScheduler

from .db import SessionLocal
from .models import Job, Content, Media, PublicationAttempt
from .integrations.facebook import FacebookPublisher
from .integrations.tiktok import (
    publish_video as tiktok_publish,
    get_status as tiktok_status,
)


YOUTUBE_UPLOAD_LEAD_SECONDS = 600
RETRY_BASE_MINUTES = 2
RETRY_MAX_MINUTES = 30


scheduler = BackgroundScheduler(
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 60,
    }
)


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resolve_publish_path(
    content: Content,
    media: Media,
) -> Path:
    path = content.rendered_media_path or media.path
    resolved = Path(path).resolve()

    if not resolved.is_relative_to(Path(settings.media_dir).resolve()):
        raise RuntimeError("Publishing path is outside MEDIA_DIR")
    if not resolved.is_file():
        raise RuntimeError(
            f"Publishing media file not found: {resolved}"
        )

    return resolved


def _youtube_due(
    job: Job,
    now: datetime,
) -> bool:
    upload_start = (
        job.publish_at
        - timedelta(seconds=YOUTUBE_UPLOAD_LEAD_SECONDS)
    )
    return upload_start <= now


def _job_is_due(
    job: Job,
    now: datetime,
) -> bool:
    if job.retry_at is not None:
        return job.retry_at <= now

    if job.platform == "youtube":
        return _youtube_due(job, now)

    return job.publish_at <= now


def _schedule_retry(
    job: Job,
    now: datetime,
) -> None:
    retry_minutes = min(
        RETRY_MAX_MINUTES,
        RETRY_BASE_MINUTES ** job.attempts,
    )

    job.status = "QUEUED"
    job.retry_at = now + timedelta(
        minutes=retry_minutes
    )


def _mark_failed(
    job: Job,
    error: str,
) -> None:
    job.status = "FAILED"
    job.error = error
    job.retry_at = None


def execute_due_jobs():
    db = SessionLocal()

    try:
        now = _utc_now_naive()

        jobs = (
            db.query(Job)
            .filter(Job.status == "QUEUED")
            .order_by(Job.publish_at.asc())
            .all()
        )

        for job in jobs:
            if not _job_is_due(job, now):
                continue

            content = db.get(Content, job.content_id)

            media = (
                db.get(Media, content.media_id)
                if content and content.media_id
                else None
            )

            if not content or not media:
                _mark_failed(
                    job,
                    "Content or media not found",
                )
                db.commit()
                continue

            # Compare-and-set across sessions/processes, not just APScheduler's in-process lock.
            claimed = db.execute(update(Job).where(Job.id == job.id, Job.status == "QUEUED").values(
                status="PUBLISHING", attempts=Job.attempts + 1, last_attempt_at=now,
                retry_at=None, error=""))
            db.commit()
            if not claimed.rowcount:
                continue
            db.refresh(job)
            attempt = PublicationAttempt(job_id=job.id, attempt=job.attempts)
            db.add(attempt)
            db.commit()

            remote_started = False
            try:
                path = _resolve_publish_path(
                    content,
                    media,
                )

                if job.platform == "facebook":
                    publisher = FacebookPublisher()
                    remote_started = True

                    if media.media_type == "video":
                        external = publisher.publish_reel(
                            str(path),
                            content.description,
                            content.hashtags,
                        )
                    else:
                        external = publisher.publish_post(
                            str(path),
                            content.description,
                            content.hashtags,
                        )

                    if not external:
                        raise RuntimeError(
                            "Facebook did not return an external ID"
                        )

                    job.external_id = str(external)
                    job.status = "PUBLISHED"
                    job.error = ""
                    content.status = "PUBLISHED"

                elif job.platform == "youtube":
                    from .integrations.youtube import (
                        publish_video as youtube_publish,
                    )

                    if media.media_type != "video":
                        raise RuntimeError(
                            "YouTube publishing requires video media"
                        )

                    youtube_publish_at = job.publish_at

                    if youtube_publish_at <= now:
                        youtube_publish_at = None

                    if not Path(settings.youtube_token_file).is_file():
                        raise RuntimeError("YouTube authorization required; run the explicit OAuth setup command.")
                    remote_started = True
                    external = youtube_publish(
                        str(path),
                        content.title,
                        content.description,
                        content.hashtags,
                        youtube_publish_at,
                    )

                    if not external:
                        raise RuntimeError(
                            "YouTube did not return a video ID"
                        )

                    job.external_id = str(external)
                    job.status = "UPLOADED" if youtube_publish_at else "PUBLISHED"
                    job.error = ""
                    content.status = job.status

                elif job.platform == "tiktok":
                    if media.media_type != "video":
                        raise RuntimeError(
                            "TikTok publishing requires video media"
                        )

                    if not settings.tiktok_access_token:
                        raise RuntimeError("TikTok access token not configured")
                    if not job.privacy_level:
                        raise RuntimeError("Legacy TikTok job needs explicit privacy selection; recreate its schedule.")
                    remote_started = True
                    external = tiktok_publish(str(path), content.title, job.privacy_level)

                    if not external:
                        raise RuntimeError(
                            "TikTok did not return a publish ID"
                        )

                    job.external_id = str(external)

                    # TikTok processing is asynchronous.
                    # Keep the job in PUBLISHING until
                    # poll_tiktok_jobs() confirms completion.
                    job.status = "PUBLISHING"
                    job.error = ""

                else:
                    raise RuntimeError(
                        f"Unsupported platform: {job.platform}"
                    )

            except Exception as exc:
                # An exception after a request may mean the remote post succeeded.
                # Never automatically re-upload an uncertain outcome.
                job.error = public_error(exc)
                if remote_started:
                    job.status = "REVIEW_REQUIRED"
                    job.error = "Publication outcome needs review before another upload: " + job.error
                    job.retry_at = None
                elif job.attempts < job.max_attempts:
                    _schedule_retry(job, now)
                else:
                    _mark_failed(job, job.error)

            attempt.status = job.status
            attempt.external_id = job.external_id
            attempt.error = job.error
            if job.status != "PUBLISHING":
                attempt.finished_at = _utc_now_naive()
            db.commit()

    finally:
        db.close()


def poll_tiktok_jobs():
    db = SessionLocal()

    try:
        jobs = (
            db.query(Job)
            .filter(
                Job.platform == "tiktok",
                Job.status == "PUBLISHING",
                Job.external_id.isnot(None),
                Job.external_id != "",
            )
            .all()
        )

        for job in jobs:
            try:
                result = tiktok_status(
                    job.external_id
                )

                status = (
                    result.get("status")
                    if result
                    else None
                )

                if status == "PUBLISH_COMPLETE":
                    job.status = "PUBLISHED"
                    job.error = ""
                    content = db.get(Content, job.content_id)
                    if content:
                        content.status = "PUBLISHED"

                elif status == "FAILED":
                    reason = (
                        result.get("fail_reason")
                        or "TikTok post processing failed"
                    )

                    job.error = (
                        f"TikTok publishing failed: {reason}"
                    )

                    job.external_id = ""
                    if job.attempts < job.max_attempts:
                        _schedule_retry(
                            job,
                            _utc_now_naive(),
                        )
                    else:
                        _mark_failed(
                            job,
                            job.error,
                        )

                # PROCESSING_UPLOAD and other non-terminal
                # states remain PUBLISHING.

                attempt = db.query(PublicationAttempt).filter(PublicationAttempt.job_id == job.id).order_by(PublicationAttempt.id.desc()).first()
                if attempt and status in {"PUBLISH_COMPLETE", "FAILED"}:
                    attempt.status = "PUBLISHED" if status == "PUBLISH_COMPLETE" else "FAILED"
                    attempt.error = job.error
                    attempt.finished_at = _utc_now_naive()
                db.commit()

            except Exception as exc:
                job.error = (
                    "TikTok status check failed: "
                    f"{public_error(exc)}"
                )
                db.commit()

    finally:
        db.close()


def start_scheduler():
    if scheduler.running:
        return

    with SessionLocal() as db:
        db.query(Job).filter(Job.status == "PUBLISHING", Job.external_id == "").update({
            Job.status: "REVIEW_REQUIRED", Job.error: "Interrupted publication. Verify platform history before reposting."})
        db.commit()

    scheduler.add_job(
        execute_due_jobs,
        "interval",
        seconds=20,
        id="publisher",
        replace_existing=True,
    )

    scheduler.add_job(
        poll_tiktok_jobs,
        "interval",
        seconds=60,
        id="tiktok_status",
        replace_existing=True,
    )

    scheduler.start()
