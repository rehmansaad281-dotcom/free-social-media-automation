from datetime import datetime, timezone, timedelta
from pathlib import Path

from apscheduler.schedulers.background import (
    BackgroundScheduler,
)

from .db import SessionLocal
from .models import Job, Content, Media
from .integrations.facebook import FacebookPublisher
from .integrations.tiktok import (
    publish_video as tiktok_publish,
    get_status as tiktok_status,
)


scheduler = BackgroundScheduler(
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 60,
    }
)


def _utc_now_naive() -> datetime:
    return datetime.now(
        timezone.utc
    ).replace(tzinfo=None)


def _resolve_publish_path(
    content: Content,
    media: Media,
) -> Path:
    path = (
        content.rendered_media_path
        or media.path
    )

    resolved = Path(path).resolve()

    if not resolved.is_file():
        raise RuntimeError(
            f"Publishing media file not found: {resolved}"
        )

    return resolved


def execute_due_jobs():
    db = SessionLocal()

    try:
        now = _utc_now_naive()

        jobs = (
            db.query(Job)
            .filter(
                Job.status == "QUEUED",
                Job.publish_at <= now,
            )
            .order_by(Job.publish_at.asc())
            .all()
        )

        for job in jobs:
            content = db.get(
                Content,
                job.content_id,
            )

            media = (
                db.get(
                    Media,
                    content.media_id,
                )
                if content
                and content.media_id
                else None
            )

            if not content or not media:
                job.status = "FAILED"
                job.error = (
                    "Content or media not found"
                )
                db.commit()
                continue

            job.status = "PUBLISHING"
            job.attempts += 1
            job.last_attempt_at = now

            db.commit()

            try:
                path = _resolve_publish_path(
                    content,
                    media,
                )

                if job.platform == "facebook":
                    publisher = FacebookPublisher()

                    if media.media_type == "video":
                        external = (
                            publisher.publish_reel(
                                str(path),
                                content.description,
                                content.hashtags,
                            )
                        )
                    else:
                        external = (
                            publisher.publish_post(
                                str(path),
                                content.description,
                                content.hashtags,
                            )
                        )

                elif job.platform == "youtube":
                    from .integrations.youtube import (
                        publish_video as youtube_publish,
                    )

                    if media.media_type != "video":
                        raise RuntimeError(
                            "YouTube publishing requires video media"
                        )

                    external = youtube_publish(
                        str(path),
                        content.title,
                        content.description,
                        content.hashtags,
                        job.publish_at,
                    )

                elif job.platform == "tiktok":
                    if media.media_type != "video":
                        raise RuntimeError(
                            "TikTok publishing requires video media"
                        )

                    external = tiktok_publish(
                        str(path),
                        content.title,
                    )

                else:
                    raise RuntimeError(
                        f"Unsupported platform: "
                        f"{job.platform}"
                    )

                if not external:
                    raise RuntimeError(
                        "Platform did not return an external ID"
                    )

                job.external_id = str(external)
                job.status = "PUBLISHED"
                job.error = ""

                content.status = "PUBLISHED"

            except Exception as exc:
                job.error = str(exc)

                if job.attempts < job.max_attempts:
                    job.status = "QUEUED"

                    retry_minutes = min(
                        30,
                        2 ** job.attempts,
                    )

                    job.publish_at = (
                        now
                        + timedelta(
                            minutes=retry_minutes
                        )
                    )
                else:
                    job.status = "FAILED"

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
                Job.status == "PUBLISHED",
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

                if status == "FAILED":
                    job.status = "FAILED"
                    job.error = (
                        "TikTok post processing failed"
                    )

                elif status == "PUBLISH_COMPLETE":
                    job.error = ""

                db.commit()

            except Exception as exc:
                # Keep the published job intact if a
                # temporary status check fails.
                job.error = (
                    f"TikTok status check failed: {exc}"
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
