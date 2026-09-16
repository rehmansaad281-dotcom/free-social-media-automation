from faster_whisper import WhisperModel
from ..config import settings

_model = None

def transcribe(path: str) -> dict:
    global _model
    if _model is None:
        _model = WhisperModel(settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type)
    segments, info = _model.transcribe(path, word_timestamps=True)
    texts, words = [], []
    for segment in segments:
        if segment.text.strip():
            texts.append(segment.text.strip())
        for word in segment.words or []:
            words.append({"word": word.word, "start": word.start, "end": word.end})
    return {"language": info.language, "text": " ".join(texts), "words": words}
