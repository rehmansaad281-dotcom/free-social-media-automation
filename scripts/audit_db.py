"""Read-only legacy integrity report: python -m scripts.audit_db."""
from sqlalchemy import text
from backend.app.db import engine

QUERIES = {
    "content_without_existing_media": "SELECT c.id FROM content c LEFT JOIN media m ON c.media_id=m.id WHERE c.media_id IS NOT NULL AND m.id IS NULL",
    "orphan_captions": "SELECT c.id FROM captions c LEFT JOIN content p ON c.content_id=p.id WHERE p.id IS NULL",
    "orphan_jobs": "SELECT j.id FROM jobs j LEFT JOIN content c ON j.content_id=c.id WHERE c.id IS NULL",
    "invalid_captions": "SELECT id FROM captions WHERE start_ms<0 OR end_ms<=start_ms OR trim(text)=''",
    "duplicate_active_jobs": "SELECT content_id, platform, count(*) FROM jobs WHERE status IN ('QUEUED','PUBLISHING','REVIEW_REQUIRED','PUBLISHED','UPLOADED') GROUP BY content_id, platform HAVING count(*)>1",
}
if __name__ == "__main__":
    with engine.connect() as connection:
        for label, query in QUERIES.items():
            rows = connection.execute(text(query)).all()
            print(f"{label}: {len(rows)}", [tuple(row) for row in rows])
