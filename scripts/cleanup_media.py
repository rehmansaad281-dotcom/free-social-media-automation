"""Offline, dry-run-first cleanup of unreferenced generated outputs only.

python -m scripts.cleanup_media [--apply] [--older-than-days 7]
"""
import argparse
import re
import time
from pathlib import Path
from filelock import FileLock
from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.models import Content, Media


def candidates(age_days=7):
    root = Path(settings.media_dir).resolve()
    with SessionLocal() as db:
        referenced = {Path(row.path).resolve() for row in db.query(Media)}
        for row in db.query(Content):
            for value in (row.voice_path, row.rendered_media_path, row.caption_audio_path):
                if value:
                    referenced.add(Path(value).resolve())
    cutoff = time.time() - age_days * 86400
    return [path for path in root.iterdir() if not path.is_symlink() and path.is_file()
        and re.fullmatch(r"(?:render_\d+_[a-f0-9]+\.mp4|voice_\d+_[a-f0-9]+\.wav)", path.name)
        and path.resolve() not in referenced and path.stat().st_mtime < cutoff]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--older-than-days", type=int, default=7)
    args = parser.parse_args()
    if args.older_than_days < 1:
        parser.error("Retention must be at least one day")
    with FileLock(settings.runtime_lock_file, timeout=0):
        for path in candidates(args.older_than_days):
            print(("Deleting " if args.apply else "Would delete ") + path.name)
            if args.apply:
                path.unlink()
