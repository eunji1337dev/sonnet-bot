"""
Модуль предметов.
"""

from __future__ import annotations

from core import database as db
from utils.formatters import format_subject


async def get_subjects_list_text() -> str:
    """Список всех предметов."""
    subjects = await db.get_all_subjects()
    if not subjects:
        return "Предметы пока не добавлены в базу. Администратор может добавить их через /add_subject."

    lines = ["Предметы первого курса:", ""]
    for i, s in enumerate(subjects, 1):
        name_sk = f" ({s['name_sk']})" if s.get("name_sk") else ""
        exam = f" — {s['exam_type']}" if s.get("exam_type") else ""
        lines.append(f"  {i}. {s['name_ru']}{name_sk}{exam}")

    lines.append("")
    lines.append("Подробнее: /subject [название]")
    return "\n".join(lines)


async def get_subject_detail_text(query: str) -> str:
    """Подробная информация по предмету."""
    subject = await db.get_subject_by_name(query)
    if not subject:
        return f"Предмет '{query}' не найден. Попробуй другое название или посмотри список: /subjects"

    text = format_subject(subject)

    # Добавить ближайший дедлайн по предмету
    deadlines = await db.get_active_deadlines()
    subject_deadlines = [
        dl for dl in deadlines if dl.get("subject_id") == subject["id"]
    ]
    if subject_deadlines:
        dl = subject_deadlines[0]
        text += f"\n\nБлижайший дедлайн: {dl['title']} — {dl['deadline_date']}"

    return text
