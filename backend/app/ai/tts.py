import subprocess
from pathlib import Path
from ..config import settings

def list_voices():
    result = []
    voice_dir = Path(settings.piper_voice_dir)
    if voice_dir.exists():
        for model in sorted(voice_dir.glob("*.onnx")):
            voice_id = model.stem
            gender = "female" if any(x in voice_id.lower() for x in ("female", "f", "amy", "lessac")) else "male"
            result.append({"voice_id": voice_id, "name": voice_id.replace("_", " ").title(), "gender": gender, "language": "unknown", "model_path": str(model)})
    if Path(settings.piper_model).exists():
        vid = Path(settings.piper_model).stem
        if not any(x["voice_id"] == vid for x in result):
            result.insert(0, {"voice_id": vid, "name": vid.replace("_", " ").title(), "gender": "neutral", "language": "unknown", "model_path": settings.piper_model})
    return result

def synthesize(text: str, output_path: str, model_path: str | None = None) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    model = model_path or settings.piper_model
    if not Path(model).exists():
        raise RuntimeError(f"Piper voice model not found: {model}")
    subprocess.run([settings.piper_bin, "--model", model, "--output_file", output_path], input=text.encode("utf-8"), check=True)
    return output_path
