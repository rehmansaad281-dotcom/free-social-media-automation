import json
import subprocess
import tempfile
from pathlib import Path

from ..config import settings


def _resolve_whisper_binary() -> Path:
    binary = Path(settings.whisper_binary)

    if not binary.is_file():
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
            f"Command failed: {details}"
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

    transcript = str(
        data.get("transcription", "")
    ).strip()

    words = []

    segments = data.get("segments", [])

    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue

            tokens = segment.get("tokens", [])

            if not isinstance(tokens, list):
                continue

            for token in tokens:
                if not isinstance(token, dict):
                    continue

                text = str(
                    token.get("text", "")
                )

                if not text.strip():
                    continue

                start = token.get("offsets", {}).get(
                    "from"
                )
                end = token.get("offsets", {}).get(
                    "to"
                )

                if start is None or end is None:
                    continue

                word = text.strip()

                if not word:
                    continue

                # Ignore Whisper special tokens.
                if word.startswith("[") and word.endswith("]"):
                    continue

                words.append(
                    {
                        "text": word,
                        "start_ms": int(start),
                        "end_ms": int(end),
                    }
                )

    language = data.get("result", {}).get(
        "language"
    )

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
