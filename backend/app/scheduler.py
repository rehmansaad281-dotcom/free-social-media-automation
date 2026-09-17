from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
from .accounts import account_context
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
    options = json.loads(job.options_json or "{}")
    if options.get("youtube_privacy", "public") != "public":
        return job.publish_at <= now
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
            now = _utc_now_naive()
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

                is_video = media.media_type == "video" or bool(content.rendered_media_path)
                options = json.loads(job.options_json or "{}")
                with account_context(job.platform, job.account_key):
                    if job.platform == "facebook":
                        publisher = FacebookPublisher()
                        remote_started = True

                        if is_video and options.get("facebook_mode", "reel") == "reel":
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
                        job.status = "PUBLISHING" if is_video else "PUBLISHED"
                        job.error = ""
                        content.status = job.status

                    elif job.platform == "youtube":
                        from .integrations.youtube import (
                            publish_video as youtube_publish,
                        )

                        if not is_video:
                            raise RuntimeError(
                                "YouTube publishing requires video media"
                            )

                        youtube_publish_at = job.publish_at

                        if youtube_publish_at <= _utc_now_naive() or options.get("youtube_privacy", "public") != "public":
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
                            privacy=options.get("youtube_privacy", "public"),
                            keywords=content.keywords,
                        )

                        if not external:
                            raise RuntimeError(
                                "YouTube did not return a video ID"
                            )

                        job.external_id = str(external)
                        job.status = "UPLOADED"
                        job.error = ""
                        content.status = job.status

                    elif job.platform == "tiktok":
                        if not is_video:
                            raise RuntimeError(
                                "TikTok publishing requires video media"
                            )

                        from .integrations.tiktok_auth import access_token
                        access_token()
                        if not job.privacy_level:
                            raise RuntimeError("Legacy TikTok job needs explicit privacy selection; recreate its schedule.")
                        remote_started = True
                        external = tiktok_publish(str(path), content.title, job.privacy_level, options=options)

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
                if _poll_expired(job):
                    _review_timeout(db, job)
                    continue
                with account_context("tiktok", job.account_key):
                    result = tiktok_status(job.external_id)

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


def _poll_expired(job):
    baseline = max(job.publish_at, job.last_attempt_at or job.created_at)
    return _utc_now_naive() > baseline + timedelta(hours=settings.platform_poll_hours)


def _record_poll_result(db, job):
    attempt = db.query(PublicationAttempt).filter_by(job_id=job.id).order_by(PublicationAttempt.id.desc()).first()
    if attempt:
        attempt.status, attempt.error, attempt.external_id = job.status, job.error, job.external_id
        if job.status in {"PUBLISHED", "FAILED", "REVIEW_REQUIRED"}:
            attempt.finished_at = _utc_now_naive()
    content = db.get(Content, job.content_id)
    if content and job.status == "PUBLISHED":
        content.status = "PUBLISHED"
    db.commit()


def _review_timeout(db, job):
    job.status = "REVIEW_REQUIRED"
    job.error = "Platform processing/status deadline exceeded. Verify the remote post; no automatic re-upload."
    _record_poll_result(db, job)


def poll_platform_jobs():
    with SessionLocal() as db:
        jobs = db.query(Job).filter(Job.platform.in_(["youtube", "facebook"]),
                    Job.status.in_(["UPLOADED", "PUBLISHING"]), Job.external_id != "").all()
        for job in jobs:
            if _poll_expired(job):
                _review_timeout(db, job)
                continue
            try:
                options = json.loads(job.options_json or "{}")
                with account_context(job.platform, job.account_key):
                    if job.platform == "youtube":
                        from .integrations.youtube import get_status
                        result = get_status(job.external_id)
                        status = result.get("status", {})
                        processing = result.get("processingDetails", {}).get("processingStatus")
                        if status.get("uploadStatus") in {"failed", "rejected", "deleted"} or processing in {"failed", "terminated"}:
                            job.status = "FAILED"
                            job.error = "YouTube rejected or failed processing this video. Inspect YouTube Studio."
                        elif status.get("uploadStatus") == "processed" and not status.get("publishAt"):
                            # Future scheduled uploads are public on success; late uploads use configured privacy.
                            attempt = job.last_attempt_at or job.created_at
                            expected = options.get("youtube_privacy") or ("public" if job.publish_at > attempt else settings.youtube_default_privacy)
                            if status.get("privacyStatus") == expected:
                                job.status, job.error = "PUBLISHED", ""
                    else:
                        status = FacebookPublisher().get_status(job.external_id)
                        phases = [status.get(name, {}).get("status") for name in ("uploading_phase", "processing_phase", "publishing_phase")]
                        if status.get("video_status") == "error" or "error" in phases:
                            job.status, job.error = "FAILED", "Facebook video processing failed. Inspect the Page video dashboard."
                        elif status.get("video_status") == "ready" and (
                            options.get("facebook_mode", "reel") == "post" or status.get("publishing_phase", {}).get("status") == "complete"
                        ):
                            job.status, job.error = "PUBLISHED", ""
                _record_poll_result(db, job)
            except Exception as exc:
                job.error = "Platform status check failed: " + public_error(exc)
                db.commit()


def start_scheduler():
    if scheduler.running:
        return

    with SessionLocal() as db:
        # Quarantine legacy duplicate active jobs without deleting owner records.
        from sqlalchemy import func
        groups = db.query(Job.content_id, Job.platform, Job.account_key).filter(
            Job.status.in_(["QUEUED", "PUBLISHING", "PUBLISHED", "UPLOADED"])).group_by(
            Job.content_id, Job.platform, Job.account_key).having(func.count(Job.id) > 1).all()
        for content_id, platform, account_key in groups:
            db.query(Job).filter(Job.content_id == content_id, Job.platform == platform,
                Job.account_key == account_key, Job.status.in_(["QUEUED", "PUBLISHING", "UPLOADED"])).update({
                    Job.status: "REVIEW_REQUIRED", Job.error: "Legacy duplicate queue entries detected. Verify remote history before retrying."})
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

    scheduler.add_job(poll_platform_jobs, "interval", seconds=60, id="platform_status", replace_existing=True)
    from .tasks import execute_media_tasks, recover_media_tasks
    recover_media_tasks()
    scheduler.add_job(execute_media_tasks, "interval", seconds=2, id="media_tasks", replace_existing=True)
    scheduler.start()
