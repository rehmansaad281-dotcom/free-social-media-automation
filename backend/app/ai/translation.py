import re
import httpx

from ..config import settings


def translate_text(
    text: str,
    source: str,
    target: str,
) -> str:
    text = text.strip()

    if not text:
        raise ValueError("Transcript cannot be empty.")

    source = source.strip()
    target = target.strip()

    if not target:
        raise ValueError(
            "Target language is required."
        )

    if not all(re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?", code) for code in (source, target)):
        raise ValueError("Use a valid source and target language code, such as en or ur.")
    if source.lower() == target.lower():
        return text
    if settings.translation_backend == "argos":
        try:
            import argostranslate.translate
        except ImportError as exc:
            raise RuntimeError("Install backend/requirements-argos.txt and the required Argos language packages.") from exc
        languages = {lang.code: lang for lang in argostranslate.translate.get_installed_languages()}
        if source not in languages or target not in languages:
            raise RuntimeError("Required Argos source/target language packages are not installed.")
        try:
            result = languages[source].get_translation(languages[target]).translate(text)
        except Exception as exc:
            raise RuntimeError("Argos translation failed; install the required language pair.") from exc
        if not result.strip():
            raise RuntimeError("Argos returned an empty translation.")
        return result
    if settings.translation_backend != "ollama":
        raise ValueError("TRANSLATION_BACKEND must be ollama or argos.")

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

    translated = data.get("response", "")
    if not isinstance(translated, str):
        raise RuntimeError("Ollama returned an invalid translation field type.")
    translated = translated.strip()

    if not translated:
        raise RuntimeError(
            "Ollama returned an empty translation."
        )

    return translated
