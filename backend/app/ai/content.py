import json

from ollama import Client

from ..config import settings


SYSTEM_PROMPT = """
You generate social-media metadata.

Return ONLY valid JSON with exactly these keys:
{
  "title": "string",
  "description": "string",
  "hashtags": ["string"],
  "keywords": ["string"]
}

Rules:
- Do not invent facts not present in the transcript.
- hashtags must be strings.
- keywords must be strings.
- title and description must be strings.
"""


def _clean_hashtags(values) -> str:
    if not isinstance(values, list):
        return ""

    result = []

    for value in values:
        text = str(value).strip()

        if not text:
            continue

        if not text.startswith("#"):
            text = f"#{text}"

        result.append(text)

    return " ".join(result)


def _clean_keywords(values) -> str:
    if not isinstance(values, list):
        return ""

    return ", ".join(
        str(value).strip()
        for value in values
        if str(value).strip()
    )


def generate_metadata(
    transcript: str,
    platform: str = "general",
) -> dict:
    if not transcript.strip():
        raise ValueError("Transcript cannot be empty.")

    client = Client(host=settings.ollama_base_url, timeout=120.0)

    try:
        response = client.chat(
            model=settings.ollama_model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (
                        f"Platform: {platform}\n\n"
                        f"Transcript:\n{transcript}"
                    ),
                },
            ],
            format="json",
        )
    except Exception as exc:
        raise RuntimeError("Ollama metadata request failed. Start Ollama and pull the configured OLLAMA_MODEL; check service connectivity.") from exc

    try:
        raw = response["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            "Ollama returned an invalid metadata response."
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Ollama returned invalid JSON for metadata."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "Ollama metadata response is not a JSON object."
        )

    if not all(isinstance(data.get(k), str) for k in ("title", "description")) or not all(
        isinstance(data.get(k), list) and all(isinstance(v, str) for v in data[k])
        for k in ("hashtags", "keywords")
    ):
        raise RuntimeError("Ollama metadata has invalid field types; retry generation.")

    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()

    if not title:
        raise RuntimeError(
            "Ollama returned an empty title."
        )

    return {
        "title": title,
        "description": description,
        "hashtags": _clean_hashtags(
            data.get("hashtags", [])
        ),
        "keywords": _clean_keywords(
            data.get("keywords", [])
        ),
    }
