import subprocess
import json
import tempfile
import shutil
from pathlib import Path

from .config import settings


def run_ffmpeg(args: list[str], cwd=None):
    command = [
        str(Path(settings.ffmpeg_bin).resolve()) if "/" in settings.ffmpeg_bin or "\\" in settings.ffmpeg_bin else settings.ffmpeg_bin,
        "-y",
        *args,
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.process_timeout,
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"FFmpeg executable not found: "
            f"{settings.ffmpeg_bin}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = (
            exc.stderr.strip()
            or exc.stdout.strip()
            or "unknown error"
        )

        raise RuntimeError(
            "FFmpeg processing failed. Check media readability, codecs, and the libass subtitle filter."
        ) from exc

    return result


def probe(path: str) -> dict:
    try:
        result = subprocess.run(
            [settings.ffprobe_bin, "-v", "error", "-protocol_whitelist", "file,pipe",
             "-format_whitelist", "mov,matroska,avi,image2,png_pipe,jpeg_pipe,webp_pipe,gif",
             "-show_streams", "-show_format", "-of", "json", str(Path(path).resolve())],
            check=True, capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise RuntimeError("FFprobe missing. Install FFmpeg and configure FFPROBE_BIN.") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ValueError("Media is unreadable or unsupported by FFprobe.") from exc
    if not isinstance(data, dict) or not data.get("streams"):
        raise ValueError("Media has no readable streams.")
    return data


def normalize_video(input_path: str, output_path: str):
    run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", input_path,
                "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:a", "aac", "-movflags", "+faststart", output_path])
    return output_path


def replace_audio(
    video_path: str,
    voice_path: str,
    output_path: str,
):
    run_ffmpeg(
        [
            "-i",
            video_path,
            "-i",
            voice_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-af", "apad",
            "-c:a",
            "aac",
            "-shortest",
            output_path,
        ]
    )

    return output_path


def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    font_size: int = 48,
):
    video = Path(video_path).resolve()
    srt = Path(srt_path).resolve()

    if not video.is_file():
        raise RuntimeError(
            f"Video file not found: {video}"
        )

    if not srt.is_file():
        raise RuntimeError(
            f"Subtitle file not found: {srt}"
        )

    vf = (
        "subtitles=captions.srt:"
        f"force_style="
        f"'FontSize={font_size},"
        f"Alignment=2,"
        f"Outline=2,"
        f"Shadow=1,"
        f"MarginV=70'"
    )

    with tempfile.TemporaryDirectory(prefix="subtitle-burn-") as temp:
        shutil.copyfile(srt, Path(temp) / "captions.srt")
        run_ffmpeg(
            [
                "-i",
                str(video),
                "-vf",
                vf,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-c:a",
                "aac",
                str(Path(output_path).resolve()),
            ], cwd=temp
        )

    return output_path


def captions_to_srt(
    captions,
    path: str,
):
    output = Path(path)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    def stamp(ms: int) -> str:
        hours, rem = divmod(
            int(ms),
            3600000,
        )

        minutes, rem = divmod(
            rem,
            60000,
        )

        seconds, milliseconds = divmod(
            rem,
            1000,
        )

        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{seconds:02d},"
            f"{milliseconds:03d}"
        )

    lines = []

    for index, caption in enumerate(
        captions,
        1,
    ):
        start_ms = int(
            caption.start_ms
        )
        end_ms = int(
            caption.end_ms
        )

        if end_ms <= start_ms:
            continue

        text = " ".join(str(caption.text).splitlines()).strip()

        if not text:
            continue

        lines.extend(
            [
                str(index),
                (
                    f"{stamp(start_ms)} --> "
                    f"{stamp(end_ms)}"
                ),
                text,
                "",
            ]
        )

    output.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return str(output)
