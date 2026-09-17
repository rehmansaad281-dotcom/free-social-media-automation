import subprocess
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
        voice_id = model.stem
        lower_id = voice_id.lower()

        if any(
            marker in lower_id
            for marker in (
                "female",
                "woman",
                "amy",
                "lessac",
            )
        ):
            gender = "female"
        elif any(
            marker in lower_id
            for marker in (
                "male",
                "man",
            )
        ):
            gender = "male"
        else:
            gender = "unknown"

        result.append(
            {
                "voice_id": voice_id,
                "name": voice_id.replace(
                    "_", " "
                ).title(),
                "gender": gender,
                "language": "unknown",
                "model_path": str(model),
            }
        )

    return result


def synthesize(
    text: str,
    output_path: str,
    model_path: str | None = None,
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

    if not model.is_file():
        raise RuntimeError(
            f"Piper voice model not found: {model}"
        )

    command = [
        settings.piper_bin,
        "--model",
        str(model),
        "--output_file",
        str(output),
    ]

    try:
        subprocess.run(
            command,
            input=text.encode("utf-8"),
            check=True,
            capture_output=True,
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
            f"Piper synthesis failed: {stderr.strip()}"
        ) from exc

    if not output.is_file():
        raise RuntimeError(
            "Piper completed but did not create "
            "the output audio file."
        )

    return str(output)
