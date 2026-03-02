"""
Обработка медиа-файлов (фото, документы, голосовые).
Пока минимальная реализация — перенаправление через AI.
"""

from __future__ import annotations

from typing import Optional
import os

import structlog
from aiogram import Router, types, F

from core.ai_engine import AIEngine, split_long_message

log = structlog.get_logger(__name__)

router = Router(name="media")

_engine: Optional[AIEngine] = None


def set_engine(engine: AIEngine) -> None:
    global _engine
    _engine = engine


@router.message(lambda m: m.photo and m.chat.type == "private")
async def handle_photo(message: types.Message) -> None:
    """Фото в ЛС — описание через заголовок."""
    if not _engine:
        return

    caption = message.caption or "Пользователь отправил фото без подписи."
    user = message.from_user
    user_id = user.id if user else 0

    answer = await _engine.generate_response(
        user_id,
        f"Пользователь отправил фото с подписью: {caption}. Ответь на основе подписи.",
        sender_name=user.first_name if user else "",
    )

    for part in split_long_message(answer):
        await message.reply(part)


@router.message(lambda m: m.document and m.chat.type == "private")
async def handle_document(message: types.Message) -> None:
    """Документы в ЛС — информация о формате."""
    await message.reply(
        "Я получил документ. Пока я не могу читать содержимое файлов, "
        "но если ты опишешь, что в нем, я помогу с обработкой."
    )


@router.message((F.voice | F.audio) & (F.chat.type == "private"))
async def handle_voice_or_audio(message: types.Message) -> None:
    """Голосовые сообщения и аудио в ЛС."""
    if not _engine:
        log.warning("handle_voice_or_audio: _engine is None")
        return

    bot = message.bot
    if not bot:
        return

    # Отправляем статус "записывает аудио" (хоть мы и распознаем)
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception as e:
        structlog.get_logger(__name__).debug("Chat action failed", error=str(e))

    prompt_msg = await message.reply(
        "⏳ <i>Слушаю и расшифровываю аудио... (это займет несколько секунд)</i>",
        parse_mode="HTML",
    )

    audio_file = message.voice or message.audio
    if not audio_file:
        await prompt_msg.edit_text("Не удалось найти аудиофайл.")
        return

    file_id = audio_file.file_id
    temp_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", f"temp_{file_id}.ogg"
    )

    try:
        # 1. Скачиваем файл
        log.info("downloading audio", file_id=file_id)
        await bot.download(file=file_id, destination=temp_path)

        # 2. Транскрибируем
        log.info("transcribing audio", path=temp_path)
        transcription = await _engine.transcribe_audio(temp_path)

        if transcription.startswith("Ошибка") or transcription.startswith(
            "Транскрибация"
        ):
            await prompt_msg.edit_text(
                f"🛑 <b>Ошибка распознавания:</b>\n{transcription}", parse_mode="HTML"
            )
            return

        if not transcription.strip():
            await prompt_msg.edit_text("🤷 Аудио распознано, но там тишина.")
            return

        # 3. Редактируем сообщение (Готово, теперь думаю)
        await prompt_msg.edit_text(
            "✅ <i>Аудио расшифровано. Готовлю конспект...</i>", parse_mode="HTML"
        )

        # 4. Отправляем транскрипцию в LLM для формирования конспекта
        user = message.from_user
        user_id = user.id if user else 0
        ai_prompt = (
            f"Я отправляю тебе полную текстовую расшифровку аудио-лекции или голосового сообщения.\n"
            f"Пожалуйста, сделай из нее красивый, четкий и структурированный конспект.\n"
            f"Обязательно выдели главные тезисы, важные даты, домашнее задание (если было озвучено) "
            f"и вопросы, которые преподаватель просил запомнить к зачету/экзамену.\n\n"
            f"ТЕКСТ РАСШИФРОВКИ:\n{transcription}"
        )

        answer = await _engine.generate_response(
            user_id,
            ai_prompt,
            sender_name=user.first_name if user else "",
        )

        # 5. Отправляем результат
        await prompt_msg.delete()  # Удаляем сообщение с процессом

        for part in split_long_message(answer):
            await message.reply(part, parse_mode="HTML")

    except Exception as e:
        log.error("error processing audio", error=str(e))
        await prompt_msg.edit_text(
            f"🛑 <b>Произошла ошибка при обработке аудио:</b>\n{e}", parse_mode="HTML"
        )

    finally:
        # Убираем за собой
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                log.warning("failed to delete temp audio", path=temp_path, error=str(e))
