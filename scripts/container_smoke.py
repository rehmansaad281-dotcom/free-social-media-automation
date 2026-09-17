"""Real container startup, FFprobe upload, rejection and rendering smoke test.

Runs inside the image with an isolated /tmp database/media and no platform tokens.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{root}/app.db", "MEDIA_DIR": str(root / "media"),
               "LOCK_DIR": str(root / "locks"), "RUNTIME_LOCK_FILE": str(root / "runtime.lock"),
               "AUTH_USERNAME": "ci", "AUTH_PASSWORD": "ephemeral-smoke-test", "SCHEDULER_ENABLED": "false"}
        server = subprocess.Popen(["python", "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8765", "--no-access-log"], env=env)
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1)
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.5)
            else:
                raise RuntimeError("Container application did not become healthy")
            authorization = "Basic " + base64.b64encode(b"ci:ephemeral-smoke-test").decode()
            def request(path, payload=None, content_type="application/json"):
                data = json.dumps(payload).encode() if payload is not None and content_type == "application/json" else payload
                req = urllib.request.Request("http://127.0.0.1:8765" + path, data=data,
                     headers={"Authorization": authorization, "Content-Type": content_type})
                with urllib.request.urlopen(req, timeout=60) as response:
                    return response.read()
            video = root / "test.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=24", "-t", "2", "-c:v", "libx264", str(video)], check=True)
            def upload(data):
                boundary = "SmokeBoundary"
                body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode() + data + f"\r\n--{boundary}--\r\n".encode()
                return json.loads(request("/api/media", body, f"multipart/form-data; boundary={boundary}"))
            media = upload(video.read_bytes())
            try:
                upload(b"not a real video")
                raise AssertionError("Unreadable media accepted")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            content = json.loads(request("/api/content", {"media_id": media["id"], "title": "Smoke"}))
            rendered = json.loads(request(f'/api/content/{content["id"]}/render', {"content_id": content["id"], "use_voiceover": False}))
            assert request(rendered["preview_url"])
            print("Real container startup, FFprobe upload/rejection, content creation, render and preview passed")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait()


if __name__ == "__main__":
    main()
