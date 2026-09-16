import json
from ollama import Client
from ..config import settings

SYSTEM_PROMPT = '''You generate social-media metadata. Return ONLY valid JSON with these keys:
title: string
description: string
hashtags: array of strings
keywords: array of strings
Do not invent facts that are not present in the transcript.'''

def generate_metadata(transcript: str, platform: str = "general") -> dict:
    client = Client(host=settings.ollama_base_url)
    response = client.chat(
        model=settings.ollama_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Platform: {platform}\nTranscript:\n{transcript}"},
        ],
        format="json",
    )
    data = json.loads(response["message"]["content"])
    return {
        "title": str(data.get("title", "")),
        "description": str(data.get("description", "")),
        "hashtags": " ".join(str(x) for x in data.get("hashtags", [])),
        "keywords": ", ".join(str(x) for x in data.get("keywords", [])),
    }
