import httpx

from ..config import settings


def translate_text(text: str, source: str, target: str) -> str:
    if not text:
        return ""

    if source.lower() == target.lower():
        return text

    prompt = (
        f"Translate the following text from {source} to {target}.\n"
        "Return only the translated text.\n"
        "Do not add explanations, labels, quotes, or commentary.\n\n"
        f"Text:\n{text}"
    )

    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    try:
        response = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Ollama translation request failed: {exc}"
        ) from exc

    data = response.json()
    translated = str(data.get("response", "")).strip()

    if not translated:
        raise RuntimeError(
            "Ollama returned an empty translation."
        )

    return translated
