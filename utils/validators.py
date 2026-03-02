"""
Валидация ввода пользователя.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

DAY_MAP = {
    "понедельник": 0,
    "пн": 0,
    "mon": 0,
    "monday": 0,
    "pondelok": 0,
    "вторник": 1,
    "вт": 1,
    "tue": 1,
    "tuesday": 1,
    "utorok": 1,
    "среда": 2,
    "ср": 2,
    "wed": 2,
    "wednesday": 2,
    "streda": 2,
    "четверг": 3,
    "чт": 3,
    "thu": 3,
    "thursday": 3,
    "stvrtok": 3,
    "пятница": 4,
    "пт": 4,
    "fri": 4,
    "friday": 4,
    "piatok": 4,
    "суббота": 5,
    "сб": 5,
    "sat": 5,
    "saturday": 5,
    "sobota": 5,
    "воскресенье": 6,
    "вс": 6,
    "sun": 6,
    "sunday": 6,
    "nedela": 6,
}

RELATIVE_DAY_MAP = {
    "сегодня": 0,
    "завтра": 1,
    "послезавтра": 2,
    "today": 0,
    "tomorrow": 1,
}


def parse_day_of_week(text: str) -> Optional[int]:
    """Распознать день недели из текста (RU/EN/SK). Возвращает 0-6 или None."""
    return DAY_MAP.get(text.lower().strip())


def parse_time(text: str) -> Optional[str]:
    """Распознать время из текста. Возвращает 'HH:MM' или None."""
    text = text.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    return None


def parse_date(text: str) -> Optional[str]:
    """Распознать дату. Поддерживает YYYY-MM-DD, DD.MM.YYYY, DD.MM. Возвращает 'YYYY-MM-DD' или None."""
    text = text.strip()

    # YYYY-MM-DD
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if match:
        try:
            datetime.strptime(text, "%Y-%m-%d")
            return text
        except ValueError:
            return None

    # DD.MM.YYYY
    match = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", text)
    if match:
        try:
            dt = datetime.strptime(text, "%d.%m.%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    # DD.MM (текущий год)
    match = re.match(r"^(\d{1,2})\.(\d{1,2})\.?$", text)
    if match:
        try:
            year = datetime.now().year
            dt = datetime(year, int(match.group(2)), int(match.group(1)))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    return None


def parse_time_delta(text: str) -> Optional[int]:
    """Распознать временной промежуток в минутах. '30m', '2h', '1h30m'. Возвращает минуты или None."""
    text = text.strip().lower()

    # Часы и минуты: 1h30m, 2h, 30m
    total = 0
    h_match = re.search(r"(\d+)\s*[hч]", text)
    m_match = re.search(r"(\d+)\s*[mм]", text)

    if h_match:
        total += int(h_match.group(1)) * 60
    if m_match:
        total += int(m_match.group(1))

    # Просто число — считаем минутами
    if not h_match and not m_match:
        try:
            total = int(text)
        except ValueError:
            return None

    return total if total > 0 else None


def validate_semester(text: str) -> Optional[str]:
    """Валидация формата семестра: winter_YYYY или summer_YYYY."""
    match = re.match(r"^(winter|summer)_(\d{4})$", text.strip().lower())
    return match.group(0) if match else None


def parse_command_args(text: str, min_args: int = 1) -> Optional[list]:
    """Разобрать аргументы команды. Возвращает список аргументов или None."""
    parts = text.strip().split(None, min_args)
    # Убрать саму команду
    if parts and parts[0].startswith("/"):
        parts = parts[1:]
    return parts if len(parts) >= min_args else None
