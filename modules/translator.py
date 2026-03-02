"""
Модуль перевода.
Перевод между RU, UA, SK через Gemini.
"""

from __future__ import annotations

from core.ai_engine import GeminiEngine


async def translate_text(engine: GeminiEngine, text: str, target_lang: str = "") -> str:
    """Перевести текст. Язык определяется автоматически."""
    prompt = (
        f"Переведи следующий текст. Определи исходный язык автоматически. "
        f"Если текст на русском — переведи на словацкий. "
        f"Если текст на словацком — переведи на русский. "
        f"Если текст на украинском — переведи на русский и словацкий. "
        f"Дай только перевод, без пояснений.\n\n"
        f"Текст: {text}"
    )

    if target_lang:
        lang_map = {
            "ru": "русский",
            "sk": "словацкий",
            "ua": "украинский",
            "en": "английский",
        }
        lang_name = lang_map.get(target_lang.lower(), target_lang)
        prompt = (
            f"Переведи следующий текст на {lang_name}. "
            f"Дай только перевод, без пояснений.\n\n"
            f"Текст: {text}"
        )

    return await engine.generate_response(0, prompt)
