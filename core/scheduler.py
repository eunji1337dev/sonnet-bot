"""
Планировщик автоматических задач.
Утреннее расписание, напоминания о дедлайнах/экзаменах, еженедельная сводка.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

import pytz
import structlog
from aiogram import Bot

from config import settings
from core import database as db
from utils.formatters import (
    format_schedule_day,
    format_weekly_summary,
)

log = structlog.get_logger(__name__)

_tz = pytz.timezone(settings.timezone)


def _now() -> datetime:
    return datetime.now(_tz)


async def scheduler_loop(bot: Bot) -> None:
    """Основной цикл планировщика. Проверяет задачи каждые 30 секунд."""
    log.info("scheduler started")
    last_morning: Optional[str] = None
    last_weekly: Optional[str] = None
    last_reminder_check: Optional[datetime] = None
    last_class_reminder_check: Optional[datetime] = None

    while True:
        try:
            now = _now()
            today_str = now.strftime("%Y-%m-%d")

            # ── Утреннее расписание (пн-пт) ──────────────
            h, m = map(int, settings.morning_schedule_time.split(":"))
            if (
                now.weekday() < 5  # Понедельник — Пятница
                and now.hour == h
                and now.minute == m
                and last_morning != today_str
                and settings.group_chat_id != 0
            ):
                last_morning = today_str
                await _send_morning_schedule(bot)

            # ── Еженедельная сводка (воскресенье) ─────────
            wh, wm = map(int, settings.weekly_summary_time.split(":"))
            if (
                now.weekday() == settings.weekly_summary_day
                and now.hour == wh
                and now.minute == wm
                and last_weekly != today_str
                and settings.group_chat_id != 0
            ):
                last_weekly = today_str
                await _send_weekly_summary(bot)

            # ── Напоминания о дедлайнах ───────────────────
            if (
                last_reminder_check is None
                or (now - last_reminder_check).total_seconds() > 3600
            ):
                last_reminder_check = now
                await _check_deadline_reminders(bot)
                await _check_exam_reminders(bot)

            # ── Напоминания о парах (за 15 минут) ─────────
            if (
                last_class_reminder_check is None
                or (now - last_class_reminder_check).total_seconds() >= 60
            ):
                last_class_reminder_check = now
                await _check_upcoming_classes(bot, now)

            # ── Личные напоминания ────────────────────────
            await _deliver_personal_reminders(bot)

        except asyncio.CancelledError:
            log.info("scheduler cancelled")
            return
        except Exception as e:
            log.exception("critical scheduler loop error", error=str(e))

        await asyncio.sleep(30)


async def _send_morning_schedule(bot: Bot) -> None:
    """Отправить расписание на сегодня."""
    try:
        now = _now()
        day = now.weekday()
        date_str = now.strftime("%Y-%m-%d")

        classes = await db.get_schedule_for_day(day)
        changes = await db.get_changes_for_date(date_str)

        if not classes:
            return  # Нет пар — не отправляем

        text = format_schedule_day(classes, changes, now)
        await bot.send_message(settings.group_chat_id, text)
        log.info("morning schedule sent", day=day)
    except Exception as e:
        log.error("failed to send morning schedule", error=str(e))


async def _send_weekly_summary(bot: Bot) -> None:
    """Отправить еженедельную сводку."""
    try:
        text = await format_weekly_summary()
        if text:
            await bot.send_message(settings.group_chat_id, text)
            log.info("weekly summary sent")
    except Exception as e:
        log.error("failed to send weekly summary", error=str(e))


async def _check_deadline_reminders(bot: Bot) -> None:
    """Отправить напоминания о дедлайнах за 3 дня, 1 день и в день дедлайна."""
    if settings.group_chat_id == 0:
        return

    try:
        today = _now().strftime("%Y-%m-%d")
        deadlines = await db.get_upcoming_deadlines(3)

        for dl in deadlines:
            dl_date = dl["deadline_date"]
            delta = (
                datetime.strptime(dl_date, "%Y-%m-%d")
                - datetime.strptime(today, "%Y-%m-%d")
            ).days

            subject = dl.get("subject_name", "")
            title = dl["title"]

            if delta == 3:
                text = f'Напоминание: до сдачи "{title}"'
                if subject:
                    text += f" ({subject})"
                text += f" осталось 3 дня (срок: {dl_date})."
            elif delta == 1:
                text = f'Напоминание: до сдачи "{title}"'
                if subject:
                    text += f" ({subject})"
                text += f" остался 1 день (срок: завтра, {dl_date})."
            elif delta == 0:
                text = f'Сегодня последний день сдачи: "{title}"'
                if subject:
                    text += f" ({subject})"
                text += "."
            else:
                continue

            await bot.send_message(settings.group_chat_id, text)
            await asyncio.sleep(0.5)

    except Exception as e:
        log.error("failed to check deadline reminders", error=str(e))


async def _check_exam_reminders(bot: Bot) -> None:
    """Отправить напоминания об экзаменах за 3 дня, 1 день и в день экзамена."""
    if settings.group_chat_id == 0:
        return

    try:
        today = _now().strftime("%Y-%m-%d")
        exams = await db.get_upcoming_exams(3)

        for exam in exams:
            exam_date = exam["exam_date"]
            delta = (
                datetime.strptime(exam_date, "%Y-%m-%d")
                - datetime.strptime(today, "%Y-%m-%d")
            ).days

            subject = exam.get("subject_name", "Экзамен")
            room = exam.get("room", "")
            exam_time = exam.get("exam_time", "")
            exam_type_raw = exam.get("exam_type", "riadny")

            type_labels = {
                "riadny": "обычный термин",
                "opravny": "пересдача",
                "druhy_opravny": "вторая пересдача",
            }
            exam_type = type_labels.get(exam_type_raw, exam_type_raw)

            if delta == 3:
                text = f'Напоминание: экзамен по предмету "{subject}" ({exam_type}) через 3 дня ({exam_date}).'
            elif delta == 1:
                text = f'Напоминание: экзамен по предмету "{subject}" ({exam_type}) завтра ({exam_date}).'
            elif delta == 0:
                text = f'Сегодня экзамен: "{subject}" ({exam_type}).'
                if exam_time:
                    text += f" Время: {exam_time}."
                if room:
                    text += f" Аудитория: {room}."
            else:
                continue

            await bot.send_message(settings.group_chat_id, text)
            await asyncio.sleep(0.5)

    except Exception as e:
        log.error("failed to check exam reminders", error=str(e))


async def _check_upcoming_classes(bot: Bot, now: datetime) -> None:
    """За 15 минут до пары отправить уведомление в группу."""
    if settings.group_chat_id == 0:
        return

    try:
        day = now.weekday()
        classes = await db.get_schedule_for_day(day)

        current_minute = now.replace(second=0, microsecond=0)
        target_minute = current_minute + timedelta(minutes=15)

        for cls in classes:
            start_time_str = cls["time_start"]
            
            # Convert string HH:MM to datetime for today
            try:
                start_h, start_m = map(int, start_time_str.split(":"))
                class_dt = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
            except ValueError:
                continue

            if class_dt == target_minute:
                subj_name = cls["subject"]
                class_type = cls["group_type"]
                room = cls.get("room", "—")

                text = (
                    f"⚠️ <b>Напоминание!</b>\n"
                    f"Через 15 минут ({start_time_str}) начнется пара:\n\n"
                    f"📚 <b>{subj_name}</b> ({class_type})\n"
                    f"🚪 Аудитория: {room}"
                )
                await bot.send_message(settings.group_chat_id, text, parse_mode="HTML")
                log.info("class reminder sent", subject=subj_name, room=room)

    except Exception as e:
        log.error("failed to check upcoming classes", error=str(e))


async def _deliver_personal_reminders(bot: Bot) -> None:
    """Доставить личные напоминания."""
    try:
        reminders = await db.get_pending_reminders()
        for r in reminders:
            try:
                text = f"Напоминание: {r['text']}"
                await bot.send_message(r["chat_id"], text)
                await db.mark_reminder_sent(r["id"])
                log.info(
                    "reminder delivered", reminder_id=r["id"], user_id=r["user_id"]
                )
            except Exception as e:
                log.error(
                    "failed to deliver reminder", reminder_id=r["id"], error=str(e)
                )
            await asyncio.sleep(0.3)
    except Exception as e:
        log.error("failed to check personal reminders", error=str(e))
