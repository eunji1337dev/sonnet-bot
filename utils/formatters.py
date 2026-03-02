"""
Форматирование сообщений бота.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytz

from config import settings
from core import database as db

_tz = pytz.timezone(settings.timezone)

DAY_NAMES_RU = [
    "понедельник",
    "вторник",
    "среду",
    "четверг",
    "пятницу",
    "субботу",
    "воскресенье",
]

DAY_NAMES_RU_NOMINATIVE = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]

MONTH_NAMES_RU = [
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def _date_label(dt: datetime) -> str:
    return f"{dt.day} {MONTH_NAMES_RU[dt.month]}"


def format_schedule_day(
    classes: List[Dict[str, Any]],
    changes: List[Dict[str, Any]],
    dt: datetime,
) -> str:
    """Форматировать расписание на конкретный день."""
    day_name = DAY_NAMES_RU_NOMINATIVE[dt.weekday()]
    date_label = _date_label(dt)

    lines = [f"Расписание на {day_name.lower()}, {date_label}", ""]

    cancelled_ids = set()
    change_notes = []

    for ch in changes:
        if ch["change_type"] == "cancelled":
            cancelled_ids.add(ch["schedule_id"])
            reason = f" ({ch['reason']})" if ch.get("reason") else ""
            change_notes.append(f"  {ch.get('subject', '?')} — отменена{reason}")
        elif ch["change_type"] == "room_change":
            change_notes.append(
                f"  {ch.get('subject', '?')} — смена аудитории: {ch.get('new_room', '?')}"
            )
        elif ch["change_type"] == "time_change":
            change_notes.append(
                f"  {ch.get('subject', '?')} — перенос на {ch.get('new_time', '?')}"
            )

    for c in classes:
        if c["id"] in cancelled_ids:
            continue
        group_label = ""
        if c["group_type"] != "all":
            group_label = f" ({c['group_type']})"

        room = f" | {c['room']}" if c.get("room") else ""
        lines.append(
            f"{c['time_start']} – {c['time_end']} | {c['subject']}{group_label}{room}"
        )

    if not any(c["id"] not in cancelled_ids for c in classes):
        lines.append("Пар нет.")

    if change_notes:
        lines.append("")
        lines.append("Изменения:")
        lines.extend(change_notes)

    return "\n".join(lines)


def format_schedule_week(
    week_data: Dict[int, List[Dict[str, Any]]],
    week_changes: Dict[str, List[Dict[str, Any]]],
    start_date: datetime,
) -> str:
    """Форматировать расписание на неделю."""
    lines = ["Расписание на неделю", ""]

    for day_offset in range(7):
        dt = start_date + timedelta(days=day_offset)
        day = dt.weekday()
        day_name = DAY_NAMES_RU_NOMINATIVE[day]
        date_str = dt.strftime("%Y-%m-%d")
        date_label = _date_label(dt)

        classes = week_data.get(day, [])
        changes = week_changes.get(date_str, [])

        if not classes and day >= 5:
            continue

        lines.append(f"-- {day_name}, {date_label} --")

        if not classes:
            lines.append("  Пар нет.")
        else:
            cancelled_ids = {
                ch["schedule_id"] for ch in changes if ch["change_type"] == "cancelled"
            }
            for c in classes:
                if c["id"] in cancelled_ids:
                    continue
                room = f" | {c['room']}" if c.get("room") else ""
                group_label = (
                    f" ({c['group_type']})" if c["group_type"] != "all" else ""
                )
                lines.append(
                    f"  {c['time_start']} – {c['time_end']} | {c['subject']}{group_label}{room}"
                )

        lines.append("")

    return "\n".join(lines).strip()


def format_subject(subject: Dict[str, Any]) -> str:
    """Форматировать информацию о предмете."""
    lines = []

    name_sk = f" ({subject['name_sk']})" if subject.get("name_sk") else ""
    lines.append(f"{subject['name_ru']}{name_sk}")
    lines.append("")

    if subject.get("teacher"):
        lines.append(f"Преподаватель: {subject['teacher']}")
    if subject.get("teacher_email"):
        lines.append(f"Email: {subject['teacher_email']}")
    if subject.get("teacher_office"):
        lines.append(f"Кабинет: {subject['teacher_office']}")
    if subject.get("exam_type"):
        lines.append(f"Формат оценки: {subject['exam_type']}")
    if subject.get("exam_description"):
        lines.append(f"Описание: {subject['exam_description']}")
    if subject.get("grade_formula"):
        lines.append(f"Формула оценки: {subject['grade_formula']}")
    if subject.get("teams_link"):
        lines.append(f"Teams: {subject['teams_link']}")
    if subject.get("materials_link"):
        lines.append(f"Материалы: {subject['materials_link']}")
    if subject.get("notes"):
        lines.append(f"Заметки: {subject['notes']}")

    return "\n".join(lines)


def format_deadlines(deadlines: List[Dict[str, Any]]) -> str:
    """Форматировать список дедлайнов."""
    if not deadlines:
        return "Активных дедлайнов нет."

    lines = ["Активные дедлайны:", ""]
    for dl in deadlines:
        subject = f" ({dl['subject_name']})" if dl.get("subject_name") else ""
        time_str = f" {dl['deadline_time']}" if dl.get("deadline_time") else ""
        desc = f" — {dl['description']}" if dl.get("description") else ""
        lines.append(
            f"  {dl['deadline_date']}{time_str} | {dl['title']}{subject}{desc}"
        )

    return "\n".join(lines)


def format_exams(exams: List[Dict[str, Any]]) -> str:
    """Форматировать список экзаменов."""
    if not exams:
        return "Информация об экзаменах пока не внесена."

    type_labels = {
        "riadny": "обычный",
        "opravny": "пересдача",
        "druhy_opravny": "2-я пересдача",
    }

    lines = ["Экзамены:", ""]
    for ex in exams:
        subject = ex.get("subject_name", "?")
        date = ex["exam_date"]
        time_str = f" {ex['exam_time']}" if ex.get("exam_time") else ""
        room = f" | Аудитория: {ex['room']}" if ex.get("room") else ""
        ex_type = type_labels.get(ex.get("exam_type", ""), ex.get("exam_type", ""))
        lines.append(f"  {date}{time_str} | {subject} ({ex_type}){room}")

    return "\n".join(lines)


def format_links(links: List[Dict[str, Any]]) -> str:
    """Форматировать список ссылок."""
    if not links:
        return "Ссылки пока не добавлены."

    lines = ["Полезные ссылки:", ""]
    current_category = None

    for link in links:
        cat = link.get("category", "Другое") or "Другое"
        if cat != current_category:
            current_category = cat
            lines.append(f"[{cat}]")

        desc = f" — {link['description']}" if link.get("description") else ""
        lines.append(f"  {link['title']}: {link['url']}{desc}")

    return "\n".join(lines)


def format_faq(notes: List[Dict[str, Any]]) -> str:
    """Форматировать FAQ."""
    if not notes:
        return "FAQ пока не заполнен."

    lines = ["Часто задаваемые вопросы:", ""]
    for i, note in enumerate(notes, 1):
        lines.append(f"{i}. {note['title']}")
        lines.append(f"   {note['content']}")
        lines.append("")

    return "\n".join(lines).strip()


def format_next_class(classes: List[Dict[str, Any]], now: datetime) -> str:
    """Найти и отформатировать ближайшую пару."""
    current_time = now.strftime("%H:%M")

    for c in classes:
        if c["time_start"] > current_time:
            room = f" | Аудитория: {c['room']}" if c.get("room") else ""
            group = f" ({c['group_type']})" if c["group_type"] != "all" else ""
            return f"Следующая пара: {c['time_start']} – {c['time_end']} | {c['subject']}{group}{room}"

    return "На сегодня пар больше нет."


async def format_weekly_summary() -> str:
    """Сформировать еженедельную сводку."""
    lines = ["Сводка на предстоящую неделю", ""]

    _now = datetime.now(pytz.timezone(settings.timezone))
    monday = _now + timedelta(days=(7 - _now.weekday()))

    # Расписание по дням
    for day_offset in range(5):
        dt = monday + timedelta(days=day_offset)
        day = dt.weekday()
        classes = await db.get_schedule_for_day(day)
        day_name = DAY_NAMES_RU_NOMINATIVE[day]
        date_label = _date_label(dt)

        if classes:
            lines.append(f"-- {day_name}, {date_label} --")
            for c in classes:
                room = f" | {c['room']}" if c.get("room") else ""
                lines.append(
                    f"  {c['time_start']} – {c['time_end']} | {c['subject']}{room}"
                )
            lines.append("")

    # Дедлайны
    deadlines = await db.get_upcoming_deadlines(7)
    if deadlines:
        lines.append("Дедлайны на этой неделе:")
        for dl in deadlines:
            subject = f" ({dl['subject_name']})" if dl.get("subject_name") else ""
            lines.append(f"  {dl['deadline_date']} | {dl['title']}{subject}")
        lines.append("")

    # Экзамены
    exams = await db.get_upcoming_exams(7)
    if exams:
        lines.append("Экзамены на этой неделе:")
        for ex in exams:
            subject = ex.get("subject_name", "?")
            lines.append(f"  {ex['exam_date']} | {subject}")
        lines.append("")

    return "\n".join(lines).strip() if len(lines) > 2 else ""


def format_stats(stats: Dict[str, Any]) -> str:
    """Форматировать статистику."""
    lines = [
        "Статистика бота:",
        "",
        f"AI-запросов: {stats.get('ai_queries', 0)}",
        f"Токенов использовано: {stats.get('total_tokens', 0) or 0}",
        f"Среднее время ответа: {int(stats.get('avg_response_ms', 0) or 0)} мс",
        f"Всего пользователей: {stats.get('total_users', 0)}",
        f"Активных за неделю: {stats.get('active_users', 0)}",
    ]
    return "\n".join(lines)


def format_poll(poll: Dict[str, Any]) -> str:
    """Форматировать результаты голосования."""
    lines = [f"Голосование: {poll['question']}", ""]

    for i, option in enumerate(poll["options"]):
        votes = poll["votes"].get(str(i), [])
        count = len(votes)
        lines.append(f"  {i + 1}. {option} — {count} голос(ов)")

    total = sum(len(v) for v in poll["votes"].values())
    lines.append(f"\nВсего голосов: {total}")

    if not poll["is_active"]:
        lines.append("(Голосование закрыто)")

    return "\n".join(lines)
