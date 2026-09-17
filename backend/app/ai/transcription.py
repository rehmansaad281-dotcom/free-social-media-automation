import json
import shutil
import os
import math
import subprocess
import tempfile
from pathlib import Path

from ..config import settings


def _resolve_whisper_binary() -> Path:
    binary = Path(shutil.which(settings.whisper_binary) or settings.whisper_binary).resolve()

    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(
            f"Whisper binary not found: {binary}"
        )

    return binary


def _resolve_whisper_model() -> Path:
    model = Path(settings.whisper_model)

    if not model.is_file():
        raise RuntimeError(
            f"Whisper model not found: {model}"
        )

    return model


def _run_command(
    command: list[str],
) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.process_timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Required executable not found: "
            f"{command[0]}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = (
            exc.stderr.strip()
            or exc.stdout.strip()
            or "unknown error"
        )

        raise RuntimeError(
            "Audio extraction or Whisper failed. Verify the input audio and installed binary/model compatibility."
        ) from exc

    return result


def _extract_audio(
    input_path: str,
    output_path: str,
):
    _run_command(
        [
            settings.ffmpeg_bin,
            "-y",
            "-protocol_whitelist", "file,pipe",
            "-i",
            input_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            output_path,
        ]
    )


def _parse_whisper_json(
    json_path: str,
) -> dict:
    path = Path(json_path)

    if not path.is_file():
        raise RuntimeError(
            f"Whisper JSON output not found: {path}"
        )

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Unable to read Whisper JSON output."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError("Whisper JSON must be an object.")
    # whisper.cpp full JSON uses a transcription ARRAY, not segments.
    segments = data.get("transcription", data.get("segments", []))
    if not isinstance(segments, list):
        raise RuntimeError("Unsupported Whisper JSON: expected transcription segments.")
    transcript = "".join(str(s.get("text", "")) for s in segments if isinstance(s, dict)).strip()
    words = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        tokens = segment.get("tokens")
        if not isinstance(tokens, list):
            raise RuntimeError("Whisper full JSON has an invalid tokens array.")
        for token in tokens:
            if not isinstance(token, dict):
                continue
            text = token.get("text", "")
            if not isinstance(text, str) or not text.strip() or text.strip().startswith("[_"):
                continue
            offsets = token.get("offsets") or {}
            if not isinstance(offsets, dict):
                continue
            start, end = offsets.get("from"), offsets.get("to")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                continue
            if not math.isfinite(start) or not math.isfinite(end):
                continue
            start, end = int(start), int(end)
            if start < 0 or end <= start:
                continue
            # Tokens are subwords. Leading whitespace starts a new word.
            if words and not text[0].isspace():
                words[-1]["text"] += text.strip()
                words[-1]["end_ms"] = max(words[-1]["end_ms"], end)
            else:
                start = max(start, words[-1]["end_ms"] if words else 0)
                if end > start:
                    words.append({"text": text.strip(), "start_ms": start, "end_ms": end})
    if not transcript:
        raise RuntimeError("Whisper detected no speech. Check the audio track and model.")
    if not words:
        raise RuntimeError("Whisper returned no valid token timestamps. Use whisper.cpp full JSON output.")

    result = data.get("result") or {}
    language = result.get("language") if isinstance(result, dict) else None

    if not language:
        language = data.get("language")

    return {
        "text": transcript,
        "language": str(language or ""),
        "words": words,
    }


def transcribe(
    input_path: str,
) -> dict:
    input_file = Path(input_path)

    if not input_file.is_file():
        raise RuntimeError(
            f"Media file not found: {input_file}"
        )

    whisper_binary = _resolve_whisper_binary()
    whisper_model = _resolve_whisper_model()

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="captagram-whisper-"
        )
    )

    audio_path = temp_dir / "audio.wav"
    output_base = temp_dir / "result"
    json_path = Path(
        f"{output_base}.json"
    )

    try:
        _extract_audio(
            str(input_file),
            str(audio_path),
        )

        _run_command(
            [
                str(whisper_binary),
                "--model",
                str(whisper_model),
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
        )

        return _parse_whisper_json(
            str(json_path)
        )

    finally:
        for path in temp_dir.iterdir():
            try:
                path.unlink()
            except OSError:
                pass

        try:
            temp_dir.rmdir()
        except OSError:
            pass
