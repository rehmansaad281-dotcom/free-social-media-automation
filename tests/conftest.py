import os
import tempfile
from pathlib import Path

# Set configuration before importing the application; never touch owner data.
ROOT = tempfile.TemporaryDirectory(prefix="automation-test-")
os.environ.update(DATABASE_URL=f"sqlite:///{ROOT.name}/app.db", MEDIA_DIR=f"{ROOT.name}/media",
                  SCHEDULER_ENABLED="false", AUTH_PASSWORD="test-password",
                  LOCK_DIR=f"{ROOT.name}/locks", RUNTIME_LOCK_FILE=f"{ROOT.name}/runtime.lock",
                  ACCOUNTS_DIR=f"{ROOT.name}/accounts", TIKTOK_TOKEN_FILE=f"{ROOT.name}/tiktok.json")

import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.db import Base, engine, init_db
from backend.app.config import settings


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    init_db()
    yield


@pytest.fixture
def client():
    with TestClient(app) as client:
        client.auth = ("owner", "test-password")
        yield client


@pytest.fixture
def ffmpeg(monkeypatch):
    import shutil
    binary = shutil.which("ffmpeg")
    if not binary:
        try:
            import imageio_ffmpeg
            binary = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pytest.skip("FFmpeg executable unavailable")
    monkeypatch.setattr(settings, "ffmpeg_bin", binary)
    return binary


@pytest.fixture
def video(ffmpeg, tmp_path):
    import subprocess
    path = tmp_path / "source.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path
