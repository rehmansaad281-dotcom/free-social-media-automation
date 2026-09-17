import subprocess
from pathlib import Path

from .config import settings


def run_ffmpeg(args: list[str]):
    command = [
        settings.ffmpeg_bin,
        "-y",
        *args,
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
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
            f"FFmpeg failed: {details}"
        ) from exc

    return result


def probe(path: str) -> dict:
    result = subprocess.run(
        [
            settings.ffmpeg_bin,
            "-i",
            path,
            "-hide_banner",
        ],
        capture_output=True,
        text=True,
    )

    return {
        "raw": result.stderr,
        "return_code": result.returncode,
    }


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
            "copy",
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

    escaped = (
        str(srt)
        .replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )

    vf = (
        f"subtitles='{escaped}':"
        f"force_style="
        f"'FontSize={font_size},"
        f"Alignment=2,"
        f"Outline=2,"
        f"Shadow=1,"
        f"MarginV=70'"
    )

    run_ffmpeg(
        [
            "-i",
            str(video),
            "-vf",
            vf,
            "-c:a",
            "copy",
            output_path,
        ]
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

        text = str(
            caption.text
        ).strip()

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
