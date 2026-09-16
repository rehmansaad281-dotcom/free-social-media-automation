import json
import subprocess
from pathlib import Path
from uuid import uuid4

from ..config import settings


def _resolve_whisper_binary() -> str:
    binary = Path(settings.whisper_binary)

    if binary.is_file():
        return str(binary)

    raise RuntimeError(
        f"Whisper binary not found: {binary}. "
        "Build whisper.cpp before starting transcription."
    )


def _resolve_whisper_model() -> str:
    model = Path(settings.whisper_model)

    if model.is_file():
        return str(model)

    raise RuntimeError(
        f"Whisper model not found: {model}. "
        "Place a GGML Whisper model at the configured path."
    )


def _run_command(command: list[str], error_message: str) -> None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(
            f"{error_message}: {exc}"
        ) from exc

    if completed.returncode != 0:
        output = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "Unknown command error"
        )

        raise RuntimeError(
            f"{error_message}: {output}"
        )


def _extract_audio(input_path: Path) -> Path:
    audio_path = (
        Path(settings.media_dir)
        / f"whisper_audio_{uuid4().hex}.wav"
    )

    command = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]

    _run_command(
        command,
        "Failed to extract audio with FFmpeg",
    )

    if not audio_path.is_file():
        raise RuntimeError(
            f"FFmpeg did not create audio file: {audio_path}"
        )

    return audio_path


def _parse_whisper_json(output_file: Path) -> dict:
    if not output_file.is_file():
        raise RuntimeError(
            f"Whisper output JSON was not created: {output_file}"
        )

    try:
        data = json.loads(
            output_file.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid Whisper JSON output: {exc}"
        ) from exc

    segments = data.get("transcription", [])

    texts = []
    words = []

    for segment in segments:
        text = str(
            segment.get("text", "")
        ).strip()

        if text:
            texts.append(text)

        for token in segment.get("tokens", []):
            if not isinstance(token, dict):
                continue

            word_text = str(
                token.get("text", "")
            ).strip()

            if not word_text:
                continue

            if word_text.startswith("[") and word_text.endswith("]"):
                continue

            offsets = token.get("offsets", {})

            start_ms = offsets.get("from")
            end_ms = offsets.get("to")

            if start_ms is None or end_ms is None:
                continue

            start = float(start_ms) / 1000.0
            end = float(end_ms) / 1000.0

            if end <= start:
                continue

            words.append(
                {
                    "word": word_text,
                    "start": start,
                    "end": end,
                }
            )

    language = (
        data.get("result", {}).get("language")
        or "unknown"
    )

    text = " ".join(texts).strip()

    if not text:
        raise RuntimeError(
            "Whisper returned an empty transcription."
        )

    return {
        "language": language,
        "text": text,
        "words": words,
    }


def transcribe(path: str) -> dict:
    input_path = Path(path)

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Media file not found: {input_path}"
        )

    whisper_binary = _resolve_whisper_binary()
    whisper_model = _resolve_whisper_model()

    Path(settings.media_dir).mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_path = None
    output_base = (
        Path(settings.media_dir)
        / f"whisper_{uuid4().hex}"
    )
    output_json = output_base.with_suffix(".json")

    try:
        audio_path = _extract_audio(input_path)

        command = [
            whisper_binary,
            "--model",
            whisper_model,
            "--file",
            str(audio_path),
            "--language",
            "auto",
            "--output-json",
            "--output-json-full",
            "--output-file",
            str(output_base),
            "--no-prints",
        ]

        _run_command(
            command,
            "Whisper transcription failed",
        )

        return _parse_whisper_json(output_json)

    finally:
        if audio_path and audio_path.is_file():
            audio_path.unlink(missing_ok=True)

        if output_json.is_file():
            output_json.unlink(missing_ok=True)
