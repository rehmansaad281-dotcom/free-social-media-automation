import subprocess
import wave
import json
from pathlib import Path

from ..config import settings


def list_voices():
    result = []

    voice_dir = Path(
        settings.piper_voice_dir
    )

    models = []

    if voice_dir.exists():
        models.extend(
            sorted(voice_dir.glob("*.onnx"))
        )

    configured_model = Path(
        settings.piper_model
    )

    if (
        configured_model.exists()
        and configured_model not in models
    ):
        models.insert(0, configured_model)

    for model in models:
        if not model.is_file() or not Path(str(model) + ".json").is_file():
            continue
        voice_id = model.stem
        try:
            config = json.loads(Path(str(model) + ".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(config, dict):
            continue
        # Voice gender is not reliably encoded in Piper filenames. Do not guess.
        gender = config.get("gender", "unknown")
        if gender not in {"male", "female", "neutral"}:
            gender = "unknown"
        language = config.get("language", {})
        language = language.get("code", "unknown") if isinstance(language, dict) else "unknown"

        result.append(
            {
                "voice_id": voice_id,
                "name": voice_id.replace(
                    "_", " "
                ).title(),
                "gender": gender,
                "language": language,
                "model_path": str(model),
                "speakers": config.get("speaker_id_map", {}),
            }
        )

    return result


def synthesize(
    text: str,
    output_path: str,
    model_path: str | None = None,
    speaker_id: int | None = None,
) -> str:
    text = text.strip()

    if not text:
        raise ValueError(
            "Text cannot be empty."
        )

    output = Path(output_path)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    model = Path(
        model_path or settings.piper_model
    )

    if not model.is_file() or not Path(str(model) + ".json").is_file():
        raise RuntimeError(
            "Piper requires both a voice .onnx model and its .onnx.json configuration."
        )

    command = [
        settings.piper_bin,
        "--model",
        str(model),
        "--output_file",
        str(output),
    ]

    config = json.loads(Path(str(model) + ".json").read_text())
    if speaker_id is not None:
        if speaker_id < 0 or speaker_id >= int(config.get("num_speakers", 1)):
            raise ValueError("Selected speaker is not present in this Piper model")
        command.extend(["--speaker", str(speaker_id)])

    try:
        subprocess.run(
            command,
            input=text.encode("utf-8"),
            check=True,
            capture_output=True,
            timeout=settings.process_timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Piper executable not found: "
            f"{settings.piper_bin}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (
            exc.stderr.decode(
                "utf-8",
                errors="replace",
            )
            if exc.stderr
            else ""
        )

        raise RuntimeError(
            "Piper synthesis failed. Check model/config compatibility and the selected voice."
        ) from exc

    if not output.is_file():
        raise RuntimeError(
            "Piper completed but did not create "
            "the output audio file."
        )

    with wave.open(str(output), "rb") as audio:
        if audio.getnframes() == 0 or audio.getframerate() <= 0:
            raise RuntimeError("Piper produced empty audio.")
    return str(output)
