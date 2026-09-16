def translate_text(text: str, source: str, target: str) -> str:
    if not text or source == target:
        return text
    import argostranslate.translate
    return argostranslate.translate.translate(text, source, target)
