from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .db import SessionLocal
from .models import Job, Content, Media
from .integrations.facebook import FacebookPublisher
from .integrations.tiktok import (
    publish_video as tiktok_publish,
    get_status as tiktok_status,
)


scheduler = BackgroundScheduler()


def execute_due_jobs():
    db = SessionLocal()

    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        jobs = (
            db.query(Job)
            .filter(
                Job.status == "QUEUED",
                Job.publish_at <= now,
            )
            .all()
        )

        for job in jobs:
            content = db.get(Content, job.content_id)

            media = (
                db.get(Media, content.media_id)
                if content and content.media_id
                else None
            )

            if not content or not media:
                job.status = "FAILED"
                job.error = "Content or media not found"
                db.commit()
                continue

            job.status = "PUBLISHING"
            job.attempts += 1
            job.last_attempt_at = now
            db.commit()

            try:
                path = content.rendered_media_path or media.path

                if job.platform == "facebook":
                    publisher = FacebookPublisher()

                    if media.media_type == "video":
                        external = publisher.publish_reel(
                            path,
                            content.description,
                            content.hashtags,
                        )
                    else:
                        external = publisher.publish_post(
                            path,
                            content.description,
                            content.hashtags,
                        )

                elif job.platform == "youtube":
                    from .integrations.youtube import (
                        publish_video as youtube_publish,
                    )

                    external = youtube_publish(
                        path,
                        content.title,
                        content.description,
                        content.hashtags,
                        job.publish_at,
                    )

                elif job.platform == "tiktok":
                    external = tiktok_publish(
                        path,
                        content.title,
                    )

                else:
                    raise RuntimeError(
                        f"Unsupported platform: {job.platform}"
                    )

                job.external_id = external
                job.status = "PUBLISHED"
                job.error = ""

                content.status = "PUBLISHED"

            except Exception as exc:
                job.error = str(exc)

                if job.attempts < job.max_attempts:
                    job.status = "QUEUED"
                    job.publish_at = (
                        now
                        + timedelta(
                            minutes=min(
                                30,
                                2 ** job.attempts,
                            )
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
                status = tiktok_status(
                    job.external_id
                ).get("status")

                if status == "FAILED":
                    job.status = "FAILED"
                    job.error = (
                        "TikTok post processing failed"
                    )

                elif status == "PUBLISH_COMPLETE":
                    job.error = ""

                db.commit()

            except Exception:
                pass

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
