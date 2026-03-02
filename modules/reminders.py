"""
Модуль напоминаний.
Личные напоминания и автоматические напоминания о дедлайнах/экзаменах.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytz

from config import settings
from core import database as db

_tz = pytz.timezone(settings.timezone)


async def add_personal_reminder(
    user_id: int, chat_id: int, text: str, minutes: int
) -> str:
    """Добавить личное напоминание."""
    remind_at = datetime.now(_tz) + timedelta(minutes=minutes)
    await db.add_reminder(user_id, chat_id, text, remind_at.isoformat())
    return f"Напоминание установлено на {remind_at.strftime('%H:%M')}."
