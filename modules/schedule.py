"""
Модуль расписания.
Логика выборки и форматирования расписания.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional

import pytz

from config import settings
from core import database as db
from utils.formatters import (
    format_next_class,
    format_schedule_day,
    format_schedule_week,
    DAY_NAMES_RU_NOMINATIVE,
)
from utils.validators import parse_day_of_week, RELATIVE_DAY_MAP

_tz = pytz.timezone(settings.timezone)


def _now() -> datetime:
    return datetime.now(_tz)


async def get_today_schedule_text(day_arg: Optional[str] = None) -> str:
    """Получить текст расписания на указанный день (или сегодня)."""
    now = _now()

    if day_arg:
        # Относительные дни
        arg_lower = day_arg.lower().strip()
        if arg_lower in RELATIVE_DAY_MAP:
            offset = RELATIVE_DAY_MAP[arg_lower]
            target_dt = now + timedelta(days=offset)
        else:
            # День недели
            day_of_week = parse_day_of_week(arg_lower)
            if day_of_week is not None:
                current_day = now.weekday()
                diff = (day_of_week - current_day) % 7
                if diff == 0 and arg_lower not in ("сегодня", "today"):
                    diff = 7  # следующая неделя
                target_dt = now + timedelta(days=diff)
            else:
                return f"Не удалось распознать день: {day_arg}. Используй название дня или 'завтра'."
    else:
        target_dt = now

    day = target_dt.weekday()
    date_str = target_dt.strftime("%Y-%m-%d")

    classes = await db.get_schedule_for_day(day)
    changes = await db.get_changes_for_date(date_str)

    if not classes:
        day_name = DAY_NAMES_RU_NOMINATIVE[day].lower()
        return f"На {day_name} пар нет."

    return format_schedule_day(classes, changes, target_dt)


async def get_week_schedule_text() -> str:
    """Получить текст расписания на текущую неделю."""
    now = _now()
    monday = now - timedelta(days=now.weekday())

    week_data: Dict[int, list] = {}
    week_changes: Dict[str, list] = {}

    for offset in range(7):
        dt = monday + timedelta(days=offset)
        day = dt.weekday()
        date_str = dt.strftime("%Y-%m-%d")

        week_data[day] = await db.get_schedule_for_day(day)
        week_changes[date_str] = await db.get_changes_for_date(date_str)

    return format_schedule_week(week_data, week_changes, monday)


async def get_full_schedule_text() -> str:
    """Получить полное расписание семестра."""
    all_classes = await db.get_full_schedule()

    if not all_classes:
        return "Расписание семестра пока не заполнено."

    lines = ["Полное расписание семестра", ""]
    current_day = -1

    for c in all_classes:
        if c["day_of_week"] != current_day:
            current_day = c["day_of_week"]
            day_name = DAY_NAMES_RU_NOMINATIVE[current_day]
            lines.append(f"-- {day_name} --")

        room = f" | {c['room']}" if c.get("room") else ""
        group = f" ({c['group_type']})" if c["group_type"] != "all" else ""
        lines.append(
            f"  {c['time_start']} – {c['time_end']} | {c['subject']}{group}{room}"
        )

    return "\n".join(lines)


async def get_next_class_text() -> str:
    """Получить текст о ближайшей паре."""
    now = _now()
    classes = await db.get_schedule_for_day(now.weekday())
    date_str = now.strftime("%Y-%m-%d")
    changes = await db.get_changes_for_date(date_str)

    # Убрать отмененные
    cancelled_ids = {
        ch["schedule_id"] for ch in changes if ch["change_type"] == "cancelled"
    }
    active_classes = [c for c in classes if c["id"] not in cancelled_ids]

    if not active_classes:
        return "На сегодня пар нет."

    return format_next_class(active_classes, now)
