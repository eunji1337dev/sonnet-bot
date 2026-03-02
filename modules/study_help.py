"""
Модуль помощи с учебой.
Объяснение тем, составление писем, генерация вопросов.
"""

from __future__ import annotations

from core.ai_engine import GeminiEngine


async def compose_letter(engine: GeminiEngine, description: str) -> str:
    """Составить формальное письмо преподавателю на словацком."""
    prompt = (
        "Составь формальное письмо преподавателю университета на словацком языке. "
        "Письмо должно быть вежливым, с правильным обращением (Vazeny pan profesor / Vazena pani profesorka). "
        "Дай только текст письма, без пояснений.\n\n"
        f"Описание ситуации: {description}"
    )
    return await engine.generate_response(0, prompt)


async def explain_topic(engine: GeminiEngine, topic: str, subject: str = "") -> str:
    """Объяснить тему из учебного курса."""
    context = f" по предмету {subject}" if subject else ""
    prompt = f"Объясни тему{context}: {topic}. Ответ должен быть понятным для студента первого курса."
    return await engine.generate_response(0, prompt)


async def generate_quiz(engine: GeminiEngine, topic: str, count: int = 5) -> str:
    """Сгенерировать вопросы для самопроверки."""
    prompt = (
        f"Составь {count} вопросов для самопроверки по теме: {topic}. "
        "Формат: номер, вопрос, затем ответ. Вопросы должны быть разного уровня сложности."
    )
    return await engine.generate_response(0, prompt)
