from datetime import datetime, timezone, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from .db import SessionLocal
from .models import Job, Content, Media
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

            job.status = "PUBLISHING"
            job.attempts += 1
            job.last_attempt_at = now
            job.retry_at = None
            job.error = ""

            db.commit()

            try:
                path = _resolve_publish_path(
                    content,
                    media,
                )

                if job.platform == "facebook":
                    publisher = FacebookPublisher()

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
                    job.status = "PUBLISHED"
                    job.error = ""
                    content.status = "PUBLISHED"

                elif job.platform == "tiktok":
                    if media.media_type != "video":
                        raise RuntimeError(
                            "TikTok publishing requires video media"
                        )

                    external = tiktok_publish(
                        str(path),
                        content.title,
                    )

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
                job.error = str(exc)

                if job.attempts < job.max_attempts:
                    _schedule_retry(job, now)
                else:
                    _mark_failed(
                        job,
                        str(exc),
                    )

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

                elif status == "FAILED":
                    reason = (
                        result.get("fail_reason")
                        or "TikTok post processing failed"
                    )

                    job.error = (
                        f"TikTok publishing failed: {reason}"
                    )

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

                db.commit()

            except Exception as exc:
                job.error = (
                    "TikTok status check failed: "
                    f"{exc}"
                )
                db.commit()

    finally:
        db.close()


def start_scheduler():
    if scheduler.running:
        return

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
