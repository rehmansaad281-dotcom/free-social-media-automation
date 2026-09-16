import json
import subprocess
from pathlib import Path

from ..config import settings


def _resolve_whisper_binary() -> str:
    binary = Path(settings.whisper_binary)

    if binary.is_file():
        return str(binary)

    raise RuntimeError(
        f"whisper-cli binary not found: {binary}. "
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


def _parse_whisper_json(output_file: Path) -> dict:
    if not output_file.is_file():
        raise RuntimeError(
            f"Whisper output JSON was not created: {output_file}"
        )

    try:
        data = json.loads(output_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid Whisper JSON output: {exc}"
        ) from exc

    segments = data.get("transcription", [])

    texts = []
    words = []

    for segment in segments:
        text = str(segment.get("text", "")).strip()

        if text:
            texts.append(text)

        for word in segment.get("tokens", []):
            if not isinstance(word, dict):
                continue

            word_text = str(word.get("text", "")).strip()

            if not word_text:
                continue

            start = word.get("offsets", {}).get("from")
            end = word.get("offsets", {}).get("to")

            if start is None or end is None:
                continue

            words.append(
                {
                    "word": word_text,
                    "start": float(start) / 100.0,
                    "end": float(end) / 100.0,
                }
            )

    language = data.get("result", {}).get("language")

    if not language:
        language = "unknown"

    return {
        "language": language,
        "text": " ".join(texts).strip(),
        "words": words,
    }


def transcribe(path: str) -> dict:
    input_path = Path(path)

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Audio/video file not found: {input_path}"
        )

    whisper_binary = _resolve_whisper_binary()
    whisper_model = _resolve_whisper_model()

    output_base = (
        Path(settings.media_dir)
        / f"whisper_{input_path.stem}"
    )

    output_json = output_base.with_suffix(".json")

    command = [
        whisper_binary,
        "--model",
        whisper_model,
        "--file",
        str(input_path),
        "--language",
        "auto",
        "--output-json",
        "--output-json-full",
        "--output-file",
        str(output_base),
        "--no-prints",
        "--flash-attn",
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Failed to start whisper-cli: {exc}"
        ) from exc

    if completed.returncode != 0:
        error_output = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "Unknown whisper-cli error"
        )

        raise RuntimeError(
            f"Whisper transcription failed: {error_output}"
        )

    result = _parse_whisper_json(output_json)

    if not result["text"]:
        raise RuntimeError("Whisper returned an empty transcription.")

    return result
