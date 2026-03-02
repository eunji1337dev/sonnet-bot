"""
Обработчики основных команд бота.
/start, /help, /schedule, /next, /exams, /deadlines, /subjects, /links, /faq,
/remind, /translate, /letter, /ask, /weather, /id и их алиасы.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

import pytz
import structlog
from aiogram import Router, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from core import database as db
from core.ai_engine import GeminiEngine, split_long_message
from modules.schedule import (
    get_today_schedule_text,
    get_week_schedule_text,
    get_next_class_text,
    get_full_schedule_text,
)
from modules.subjects import get_subjects_list_text, get_subject_detail_text
from modules.translator import translate_text
from modules.study_help import compose_letter
from utils.formatters import format_deadlines, format_exams, format_faq, format_links
from utils.validators import parse_time_delta

log = structlog.get_logger(__name__)

router = Router(name="commands")

_tz = pytz.timezone(settings.timezone)
_engine: Optional[GeminiEngine] = None


def set_engine(engine: GeminiEngine) -> None:
    global _engine
    _engine = engine


def _now() -> datetime:
    return datetime.now(_tz)


# ═══════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════


@router.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    user = message.from_user
    if user:
        await db.upsert_user(
            user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
        )

    text = (
        "Sonnet — AI-ассистент группы Europske studia.\n\n"
        "Я могу помочь с расписанием, экзаменами, дедлайнами, переводом и учебными вопросами.\n\n"
        "Основные возможности:\n"
        "- Расписание и отмены пар\n"
        "- Информация по предметам и экзаменам\n"
        "- Дедлайны и напоминания\n"
        "- Ответы на вопросы по учебе\n"
        "- Перевод RU/UA/SK\n"
        "- Составление писем преподавателям\n\n"
        "Для справки по командам: /help\n"
        'Чтобы задать вопрос: напиши "Sonnet, ..." в группе или напиши мне в личные сообщения.'
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Расписание", callback_data="menu_schedule"),
                InlineKeyboardButton(text="Экзамены", callback_data="menu_exams"),
                InlineKeyboardButton(text="Дедлайны", callback_data="menu_deadlines"),
            ],
            [
                InlineKeyboardButton(text="Предметы", callback_data="menu_subjects"),
                InlineKeyboardButton(text="Ссылки", callback_data="menu_links"),
                InlineKeyboardButton(text="FAQ", callback_data="menu_faq"),
            ],
            [
                InlineKeyboardButton(text="Помощь", callback_data="menu_help"),
            ],
        ]
    )

    await message.answer(text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════════
# /help
# ═══════════════════════════════════════════════════════

HELP_TEXT = (
    "Команды Sonnet:\n\n"
    "Расписание:\n"
    "  /schedule (/s) — расписание на сегодня\n"
    "  /schedule завтра — расписание на завтра\n"
    "  /schedule понедельник — расписание на конкретный день\n"
    "  /schedule_week (/sw) — расписание на неделю\n"
    "  /schedule_full — полное расписание семестра\n"
    "  /next (/n) — ближайшая пара\n\n"
    "Учеба:\n"
    "  /exams (/e) — экзамены и пересдачи\n"
    "  /deadlines (/d) — активные дедлайны\n"
    "  /subjects — список предметов\n"
    "  /subject [название] — информация по предмету\n"
    "  /links — полезные ссылки\n"
    "  /faq — часто задаваемые вопросы\n\n"
    "AI-помощь:\n"
    "  /ask (/a) [вопрос] — задать вопрос AI\n"
    "  /translate (/t) [текст] — перевод RU/UA/SK\n"
    "  /letter [текст] — составить письмо преподавателю на SK\n\n"
    "Другое:\n"
    "  /remind [время] [текст] — напоминание (30m, 2h, 1h30m)\n"
    "  /weather — погода в Прешове\n"
    "  /id — твой Telegram ID\n"
    "  /help — эта справка\n\n"
    'Или просто напиши "Sonnet, ..." в группе.'
)


@router.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    await message.answer(HELP_TEXT)


# ═══════════════════════════════════════════════════════
# SCHEDULE
# ═══════════════════════════════════════════════════════


@router.message(Command("schedule", "s"))
async def cmd_schedule(message: types.Message) -> None:
    args = (message.text or "").split(None, 1)
    day_arg = args[1].strip() if len(args) > 1 else None
    text = await get_today_schedule_text(day_arg)
    await message.answer(text)


@router.message(Command("schedule_week", "sw"))
async def cmd_schedule_week(message: types.Message) -> None:
    text = await get_week_schedule_text()
    for part in split_long_message(text):
        await message.answer(part)
        await asyncio.sleep(0.3)


@router.message(Command("schedule_full"))
async def cmd_schedule_full(message: types.Message) -> None:
    text = await get_full_schedule_text()
    for part in split_long_message(text):
        await message.answer(part)
        await asyncio.sleep(0.3)


@router.message(Command("next", "n"))
async def cmd_next(message: types.Message) -> None:
    text = await get_next_class_text()
    await message.answer(text)


# ═══════════════════════════════════════════════════════
# EXAMS / DEADLINES
# ═══════════════════════════════════════════════════════


@router.message(Command("exams", "e"))
async def cmd_exams(message: types.Message) -> None:
    exams = await db.get_upcoming_exams(90)
    text = format_exams(exams)
    await message.answer(text)


@router.message(Command("deadlines", "d"))
async def cmd_deadlines(message: types.Message) -> None:
    deadlines = await db.get_active_deadlines()
    text = format_deadlines(deadlines)
    await message.answer(text)


# ═══════════════════════════════════════════════════════
# SUBJECTS
# ═══════════════════════════════════════════════════════


@router.message(Command("subjects"))
async def cmd_subjects(message: types.Message) -> None:
    text = await get_subjects_list_text()
    await message.answer(text)


@router.message(Command("subject"))
async def cmd_subject(message: types.Message) -> None:
    args = (message.text or "").split(None, 1)
    if len(args) < 2:
        await message.answer("Укажи название предмета: /subject [название]")
        return
    text = await get_subject_detail_text(args[1])
    await message.answer(text)


# ═══════════════════════════════════════════════════════
# LINKS / FAQ
# ═══════════════════════════════════════════════════════


@router.message(Command("links"))
async def cmd_links(message: types.Message) -> None:
    links = await db.get_all_links()
    text = format_links(links)
    await message.answer(text)


@router.message(Command("faq"))
async def cmd_faq(message: types.Message) -> None:
    notes = await db.get_notes_by_category("faq")
    text = format_faq(notes)
    for part in split_long_message(text):
        await message.answer(part)
        await asyncio.sleep(0.3)


# ═══════════════════════════════════════════════════════
# REMIND
# ═══════════════════════════════════════════════════════


@router.message(Command("remind"))
async def cmd_remind(message: types.Message) -> None:
    args = (message.text or "").split(None, 2)
    if len(args) < 3:
        await message.answer(
            "Формат: /remind [время] [текст]\nПример: /remind 2h Проверить Teams"
        )
        return

    minutes = parse_time_delta(args[1])
    if not minutes:
        await message.answer(
            "Не удалось распознать время. Используй формат: 30m, 2h, 1h30m"
        )
        return

    remind_at = _now() + timedelta(minutes=minutes)
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id

    await db.add_reminder(user_id, chat_id, args[2], remind_at.isoformat())
    await message.answer(
        f"Напоминание установлено на {remind_at.strftime('%H:%M')} ({args[1]})."
    )


# ═══════════════════════════════════════════════════════
# TRANSLATE / LETTER
# ═══════════════════════════════════════════════════════


@router.message(Command("translate", "t"))
async def cmd_translate(message: types.Message) -> None:
    args = (message.text or "").split(None, 1)
    if len(args) < 2:
        await message.answer("Укажи текст: /translate [текст]")
        return

    if not _engine:
        await message.answer("AI-модуль не инициализирован.")
        return

    text = await translate_text(_engine, args[1])
    await message.answer(text)


@router.message(Command("letter"))
async def cmd_letter(message: types.Message) -> None:
    args = (message.text or "").split(None, 1)
    if len(args) < 2:
        await message.answer("Укажи описание письма на русском: /letter [текст]")
        return

    if not _engine:
        await message.answer("AI-модуль не инициализирован.")
        return

    text = await compose_letter(_engine, args[1])
    await message.answer(text)


# ═══════════════════════════════════════════════════════
# ASK (прямой запрос к AI)
# ═══════════════════════════════════════════════════════


@router.message(Command("ask", "a"))
async def cmd_ask(message: types.Message) -> None:
    args = (message.text or "").split(None, 1)
    if len(args) < 2:
        await message.answer("Задай вопрос: /ask [вопрос]")
        return

    if not _engine:
        await message.answer("AI-модуль не инициализирован.")
        return

    user = message.from_user
    user_id = user.id if user else 0
    sender = user.first_name if user else ""

    # Контекст из базы
    db_context = await _build_db_context(args[1])

    answer = await _engine.generate_response(
        user_id, args[1], db_context=db_context, sender_name=sender
    )

    # Логируем
    await db.log_ai_request(user_id, args[1], answer)

    for part in split_long_message(answer):
        await message.answer(part)
        await asyncio.sleep(0.3)


# ═══════════════════════════════════════════════════════
# WEATHER
# ═══════════════════════════════════════════════════════


@router.message(Command("weather"))
async def cmd_weather(message: types.Message) -> None:
    if not _engine:
        await message.answer("AI-модуль не инициализирован.")
        return

    user_id = message.from_user.id if message.from_user else 0
    bot = message.bot
    if bot:
        try:
            await bot.send_chat_action(message.chat.id, "typing")
        except Exception as e:
            structlog.get_logger(__name__).debug(
                "Weather typing action failed", error=str(e)
            )

    # Координаты Прешова, Словакия
    lat, lon = 48.9984, 21.2339
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&current_weather=true"
        f"&hourly=temperature_2m,precipitation_probability"
        f"&timezone=Europe%2FBerlin&forecast_days=1"
    )

    import aiohttp

    weather_text = (
        "Не удалось получить точные данные, сымпровизируй прогноз для Прешова."
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    current = data.get("current_weather", {})
                    temp = current.get("temperature", "?")
                    wind = current.get("windspeed", "?")

                    weather_text = (
                        f"Сейчас в Прешове: Температура {temp}°C, Ветер {wind} км/ч.\n"
                        f"Основываясь на этих точных данных, составь короткий, полезный и заботливый "
                        f"прогноз погоды для студентов (нужно ли брать зонт, тепло ли одеваться)."
                    )
    except Exception as e:
        log.error("failed to fetch weather", error=str(e))

    answer = await _engine.generate_response(user_id, weather_text)

    if answer:
        await message.answer(answer)
    else:
        await message.answer(
            "🌤 Не смог связаться со спутниками погоды. Посмотри в окно!"
        )


# ═══════════════════════════════════════════════════════
# ID
# ═══════════════════════════════════════════════════════


@router.message(Command("id"))
async def cmd_id(message: types.Message) -> None:
    user = message.from_user
    text = f"Твой Telegram ID: {user.id}" if user else "Не удалось определить ID."
    if message.chat.type != "private":
        text += f"\nID чата: {message.chat.id}"
    await message.answer(text)


# ═══════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════


async def _build_db_context(question: str) -> str:
    """Собрать контекст из базы данных для AI-запроса."""
    context_parts = []
    q_lower = question.lower()

    # Расписание
    schedule_keywords = [
        "пара",
        "расписание",
        "пары",
        "занятие",
        "лекция",
        "schedule",
        "class",
    ]
    if any(kw in q_lower for kw in schedule_keywords):
        now = _now()
        classes = await db.get_schedule_for_day(now.weekday())
        if classes:
            context_parts.append("Расписание на сегодня:")
            for c in classes:
                context_parts.append(
                    f"  {c['time_start']}-{c['time_end']} {c['subject']} ({c.get('room', '')})"
                )

    # Экзамены
    exam_keywords = ["экзамен", "exams", "пересдача", "termin", "зачет"]
    if any(kw in q_lower for kw in exam_keywords):
        exams = await db.get_upcoming_exams(60)
        if exams:
            context_parts.append("Ближайшие экзамены:")
            for ex in exams:
                context_parts.append(
                    f"  {ex['exam_date']} — {ex.get('subject_name', '?')} ({ex.get('exam_type', '')})"
                )

    # Дедлайны
    deadline_keywords = ["дедлайн", "deadline", "сдача", "срок", "сдать"]
    if any(kw in q_lower for kw in deadline_keywords):
        deadlines = await db.get_active_deadlines()
        if deadlines:
            context_parts.append("Активные дедлайны:")
            for dl in deadlines:
                context_parts.append(f"  {dl['deadline_date']} — {dl['title']}")

    # Предметы
    subjects = await db.get_all_subjects()
    for subj in subjects:
        name_lower = (
            subj.get("name_ru", "") + " " + (subj.get("name_sk", "") or "")
        ).lower()
        if any(word in q_lower for word in name_lower.split() if len(word) > 3):
            context_parts.append(f"Предмет: {subj['name_ru']}")
            if subj.get("teacher"):
                context_parts.append(f"  Преподаватель: {subj['teacher']}")
            if subj.get("exam_type"):
                context_parts.append(f"  Формат: {subj['exam_type']}")
            if subj.get("exam_description"):
                context_parts.append(f"  Описание: {subj['exam_description']}")
            break

    # Память (заметки "запомни:")
    try:
        all_notes = await db.get_notes_by_category("memory")
        if all_notes:
            context_parts.append("\n=== СОХРАНЁННЫЕ ЗАМЕТКИ ===")
            for note in all_notes:
                context_parts.append(f"- {note.get('content', '')}")
    except Exception as e:
        structlog.get_logger(__name__).error(
            "Context notes fetcher failed", error=str(e)
        )

    return "\n".join(context_parts)
