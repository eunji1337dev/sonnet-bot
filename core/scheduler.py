from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import pytz
import structlog
from aiogram import Bot

from apscheduler.schedulers.asyncio import AsyncIOScheduler
# We use SQLAlchemy for simple persistent storage of jobs
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
# We use in-memory just for the transient class timers, but we'll use DB for reminders
from apscheduler.jobstores.memory import MemoryJobStore

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


class EnterpriseScheduler:
    """99.99% Reliable APScheduler with persistent DB store."""

    def __init__(self, bot: Bot):
        self.bot = bot
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(settings.database_path) or ".", exist_ok=True)
        jobs_db_url = f"sqlite:///{os.path.dirname(settings.database_path)}/jobs.sqlite"

        jobstores = {
            'default': SQLAlchemyJobStore(url=jobs_db_url),
            'transient': MemoryJobStore() # For dynamically computed class reminders
        }
        
        job_defaults = {
            'misfire_grace_time': 300, # 5 minutes grace for container restarts
            'coalesce': True,
            'max_instances': 1
        }
        
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores, 
            job_defaults=job_defaults,
            timezone=_tz
        )
        self._init_jobs()
        log.info("Enterprise scheduler initialized", store=jobs_db_url)

    def _init_jobs(self):
        """Set up the deterministic hardcoded schedules."""
        
        # ── Утреннее расписание (пн-пт) ──────────────
        mh, mm = map(int, settings.morning_schedule_time.split(":"))
        self.scheduler.add_job(
            self._send_morning_schedule,
            'cron',
            day_of_week='mon-fri',
            hour=mh, minute=mm,
            id='morning_schedule',
            replace_existing=True,
            jobstore='default'
        )

        # ── Еженедельная сводка (воскресенье) ─────────
        wh, wm = map(int, settings.weekly_summary_time.split(":"))
        # We assume weekly_summary_day is 0-6. In APScheduler: mon,tue,wed,thu,fri,sat,sun
        days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        target_day = days[settings.weekly_summary_day] if 0 <= settings.weekly_summary_day <= 6 else 'sun'
        
        self.scheduler.add_job(
            self._send_weekly_summary,
            'cron',
            day_of_week=target_day,
            hour=wh, minute=wm,
            id='weekly_summary',
            replace_existing=True,
            jobstore='default'
        )
        
        # ── Напоминания о дедлайнах и расписании ──────
        # Run an audit every 5 minutes to schedule upcoming class triggers specifically
        self.scheduler.add_job(
            self._audit_and_schedule_classes,
            'interval',
            minutes=5,
            id='audit_classes',
            replace_existing=True,
            jobstore='default'
        )
        
        # Personal Reminders processor every minute
        self.scheduler.add_job(
            self._process_personal_reminders,
            'interval',
            minutes=1,
            id='personal_reminders_processor',
            replace_existing=True,
            jobstore='default'
        )

    def start(self):
        self.scheduler.start()
        log.info("Enterprise scheduler started successfully")

    def shutdown(self):
        self.scheduler.shutdown()
        log.info("Enterprise scheduler shutdown successfully")

    # ═══════════════════════════════════════════════════════
    # JOBS
    # ═══════════════════════════════════════════════════════

    async def _send_morning_schedule(self) -> None:
        """Отправить расписание на сегодня."""
        if settings.group_chat_id == 0:
            return
            
        try:
            now = _now()
            day = now.weekday()
            date_str = now.strftime("%Y-%m-%d")

            classes = await db.get_schedule_for_day(day)
            changes = await db.get_changes_for_date(date_str)

            if not classes:
                return  # Нет пар — не отправляем

            text = format_schedule_day(classes, changes, now)
            await self.bot.send_message(settings.group_chat_id, text)
            log.info("morning schedule sent", day=day)
        except Exception as e:
            log.error("failed to send morning schedule", error=str(e))


    async def _send_weekly_summary(self) -> None:
        """Отправить еженедельную сводку."""
        if settings.group_chat_id == 0:
            return
            
        try:
            text = await format_weekly_summary()
            if text:
                await self.bot.send_message(settings.group_chat_id, text)
                log.info("weekly summary sent")
        except Exception as e:
            log.error("failed to send weekly summary", error=str(e))


    async def _audit_and_schedule_classes(self) -> None:
        """
        Runs every 5 minutes. Looks at classes starting in the next ~10-25 mins.
        We dynamically schedule a strict one-off job exactly 15 mins before class time.
        """
        if settings.group_chat_id == 0:
            return

        try:
            now = _now()
            day = now.weekday()
            classes = await db.get_schedule_for_day(day)
            
            for cls in classes:
                start_time_str = cls["time_start"]
                try:
                    start_h, start_m = map(int, start_time_str.split(":"))
                    class_time = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
                except ValueError:
                    continue
                
                # We need to notify EXACTLY 15 mins before.
                notification_time = class_time - timedelta(minutes=15)
                
                # Check if this notification_time is within the NEXT 6 minutes
                # to prevent scheduling duplications too far in advance in transient store
                time_until_notif = (notification_time - now).total_seconds()
                
                if 0 <= time_until_notif <= 360: # Within next 6 minutes
                    job_id = f"class_reminder_{day}_{start_time_str}_{cls['id']}"
                    
                    # Schedule it explicitly
                    self.scheduler.add_job(
                        self._trigger_class_notification,
                        'date',
                        run_date=notification_time,
                        args=[start_time_str, cls["subject"], cls["group_type"], cls.get("room", "—")],
                        id=job_id,
                        replace_existing=True,
                        jobstore='transient',
                        misfire_grace_time=120 # Better 2 mins late than never
                    )
                    
            # Check Deadline/Exam Reminders once a day around noon
            if now.hour == 12 and 0 <= now.minute < 5:
                # We do this every 5 minutes from 12:00 to 12:05, so just pick one run
                if now.minute == 0 or now.minute == 1:
                     await self._check_deadline_reminders()
                     await self._check_exam_reminders()
                     
        except Exception as e:
            log.error("failed to audit upcoming classes", error=str(e))

    async def _trigger_class_notification(self, start_time: str, subj_name: str, class_type: str, room: str) -> None:
        """The exact 15-minute scheduled call."""
        text = (
            f"⚠️ <b>Напоминание!</b>\n"
            f"Через 15 минут ({start_time}) начнется пара:\n\n"
            f"📚 <b>{subj_name}</b> ({class_type})\n"
            f"🚪 Аудитория: {room}"
        )
        try:
            await self.bot.send_message(settings.group_chat_id, text, parse_mode="HTML")
            log.info("class reminder sent deterministically", subject=subj_name, room=room)
        except Exception as e:
             log.error("failed to send deterministic class reminder", error=str(e))

    async def _process_personal_reminders(self) -> None:
        """Доставить личные напоминания."""
        try:
            reminders = await db.get_pending_reminders()
            for r in reminders:
                try:
                    text = f"Напоминание: {r['text']}"
                    await self.bot.send_message(r["chat_id"], text)
                    await db.mark_reminder_sent(r["id"])
                    log.info("reminder delivered", reminder_id=r["id"], user_id=r["user_id"])
                except Exception as e:
                    log.error("failed to deliver reminder", reminder_id=r["id"], error=str(e))
        except Exception as e:
            log.error("failed to check personal reminders", error=str(e))

    async def _check_deadline_reminders(self) -> None:
        """Send 3, 1, 0 day deadline reminders."""
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
                    if subject: text += f" ({subject})"
                    text += f" осталось 3 дня (срок: {dl_date})."
                elif delta == 1:
                    text = f'Напоминание: до сдачи "{title}"'
                    if subject: text += f" ({subject})"
                    text += f" остался 1 день (срок: завтра, {dl_date})."
                elif delta == 0:
                    text = f'Сегодня последний день сдачи: "{title}"'
                    if subject: text += f" ({subject})"
                    text += "."
                else:
                    continue

                await self.bot.send_message(settings.group_chat_id, text)
        except Exception as e:
            log.error("failed to check deadline reminders", error=str(e))

    async def _check_exam_reminders(self) -> None:
        """Send 3, 1, 0 day exam reminders."""
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
                    if exam_time: text += f" Время: {exam_time}."
                    if room: text += f" Аудитория: {room}."
                else:
                    continue

                await self.bot.send_message(settings.group_chat_id, text)
        except Exception as e:
            log.error("failed to check exam reminders", error=str(e))


# Backward compatibility for main.py importing old structure
async def scheduler_loop(bot: Bot) -> None:
    scheduler = EnterpriseScheduler(bot)
    scheduler.start()
    
    # Just hold the loop so the task doesn't finish
    try:
        import asyncio
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        scheduler.shutdown()
        log.info("Scheduler task cancelled from top-level loop")
