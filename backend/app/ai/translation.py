import httpx

from ..config import settings


def translate_text(
    text: str,
    source: str,
    target: str,
) -> str:
    text = text.strip()

    if not text:
        return ""

    source = source.strip()
    target = target.strip()

    if not target:
        raise ValueError(
            "Target language is required."
        )

    if source and source.lower() == target.lower():
        return text

    prompt = (
        f"Translate the following text from {source or 'the source language'} "
        f"to {target}.\n"
        "Return only the translated text.\n"
        "Do not add explanations, labels, quotes, or commentary.\n\n"
        f"Text:\n{text}"
    )

    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    url = (
        f"{settings.ollama_base_url.rstrip('/')}"
        "/api/generate"
    )

    try:
        response = httpx.post(
            url,
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Ollama translation request failed: {exc}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Ollama returned invalid JSON."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "Ollama returned an invalid translation response."
        )

    translated = str(
        data.get("response", "")
    ).strip()

    if not translated:
        raise RuntimeError(
            "Ollama returned an empty translation."
        )

    return translated
