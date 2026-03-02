"""
Административные команды.
Управление расписанием, дедлайнами, экзаменами, предметами, ролями.
"""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from core import database as db
from utils.formatters import format_poll, format_stats
from utils.permissions import require_role
from utils.validators import parse_date, parse_day_of_week, parse_time

log = structlog.get_logger(__name__)

router = Router(name="admin")


# ═══════════════════════════════════════════════════════
# /admin
# ═══════════════════════════════════════════════════════


@router.message(Command("admin"))
@require_role("admin")
async def cmd_admin(message: types.Message) -> None:
    text = "Панель администратора"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="Управление", callback_data="admin_manage")],
        ]
    )
    await message.answer(text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════════
# SCHEDULE MANAGEMENT
# ═══════════════════════════════════════════════════════


@router.message(Command("add_class"))
@require_role("admin")
async def cmd_add_class(message: types.Message) -> None:
    """Формат: /add_class [день] [начало] [конец] [предмет] [аудитория]"""
    args = (message.text or "").split(None, 5)
    if len(args) < 5:
        await message.answer(
            "Формат: /add_class [день] [начало] [конец] [предмет] [аудитория]\n"
            "Пример: /add_class понедельник 09:45 11:15 Slovensky jazyk A2"
        )
        return

    day = parse_day_of_week(args[1])
    if day is None:
        await message.answer("Не удалось распознать день недели.")
        return

    time_start = parse_time(args[2])
    time_end = parse_time(args[3])
    if not time_start or not time_end:
        await message.answer("Неверный формат времени. Используй HH:MM.")
        return

    subject = args[4]
    room = args[5] if len(args) > 5 else ""

    entry_id = await db.add_schedule_entry(
        day, time_start, time_end, subject, room=room
    )
    await message.answer(
        f"Пара добавлена (ID: {entry_id}): {subject}, {time_start}-{time_end}."
    )


@router.message(Command("edit_class"))
@require_role("admin")
async def cmd_edit_class(message: types.Message) -> None:
    """Формат: /edit_class [id] [параметр] [значение]"""
    args = (message.text or "").split(None, 3)
    if len(args) < 4:
        await message.answer(
            "Формат: /edit_class [id] [параметр] [значение]\n"
            "Параметры: subject, room, teacher, time_start, time_end, group_type\n"
            "Пример: /edit_class 1 room B3"
        )
        return

    try:
        entry_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    success = await db.update_schedule_entry(entry_id, args[2], args[3])
    if success:
        await message.answer(f"Пара {entry_id} обновлена: {args[2]} = {args[3]}.")
    else:
        await message.answer("Не удалось обновить. Проверь ID и название параметра.")


@router.message(Command("remove_class"))
@require_role("admin")
async def cmd_remove_class(message: types.Message) -> None:
    """Формат: /remove_class [id]"""
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Формат: /remove_class [id]")
        return

    try:
        entry_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    success = await db.remove_schedule_entry(entry_id)
    if success:
        await message.answer(f"Пара {entry_id} удалена.")
    else:
        await message.answer("Пара не найдена.")


@router.message(Command("cancel_class"))
@require_role("moderator")
async def cmd_cancel_class(message: types.Message) -> None:
    """Формат: /cancel_class [предмет] [дата] [причина]"""
    args = (message.text or "").split(None, 3)
    if len(args) < 3:
        await message.answer(
            "Формат: /cancel_class [предмет] [дата] [причина]\n"
            "Пример: /cancel_class Logika 2025-12-15 Преподаватель болен"
        )
        return

    date_str = parse_date(args[2])
    if not date_str:
        await message.answer(
            "Неверный формат даты. Используй YYYY-MM-DD или DD.MM.YYYY."
        )
        return

    # Найти schedule_id по предмету
    from datetime import datetime

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    classes = await db.get_schedule_for_day(dt.weekday())
    subject_query = args[1].lower()

    schedule_id = None
    for c in classes:
        if (
            subject_query in c["subject"].lower()
            or subject_query in (c.get("subject_sk") or "").lower()
        ):
            schedule_id = c["id"]
            break

    if schedule_id is None:
        await message.answer(f"Не найдена пара '{args[1]}' в этот день.")
        return

    reason = args[3] if len(args) > 3 else ""
    sender = message.from_user.first_name if message.from_user else ""

    await db.add_schedule_change(
        schedule_id, date_str, "cancelled", reason=reason, announced_by=sender
    )
    await message.answer(f"Отмена записана: {args[1]} на {date_str}.")

    # Уведомить группу
    if settings.group_chat_id != 0 and message.chat.id != settings.group_chat_id:
        reason_text = f" ({reason})" if reason else ""
        try:
            await message.bot.send_message(  # type: ignore[union-attr]
                settings.group_chat_id,
                f"Отмена пары: {args[1]} {date_str}{reason_text}.",
            )
        except Exception as e:
            log.error("failed to notify group about cancellation", error=str(e))


@router.message(Command("move_class"))
@require_role("moderator")
async def cmd_move_class(message: types.Message) -> None:
    """Формат: /move_class [предмет] [дата] [новое_время_или_аудитория]"""
    args = (message.text or "").split(None, 3)
    if len(args) < 4:
        await message.answer(
            "Формат: /move_class [предмет] [дата] [новое_время_или_аудитория]\n"
            "Пример: /move_class Logika 2025-12-15 14:00"
        )
        return

    date_str = parse_date(args[2])
    if not date_str:
        await message.answer("Неверный формат даты.")
        return

    from datetime import datetime

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    classes = await db.get_schedule_for_day(dt.weekday())
    subject_query = args[1].lower()

    schedule_id = None
    for c in classes:
        if subject_query in c["subject"].lower():
            schedule_id = c["id"]
            break

    if schedule_id is None:
        await message.answer(f"Не найдена пара '{args[1]}' в этот день.")
        return

    new_value = args[3]
    # Определяем: время или аудитория
    if parse_time(new_value):
        change_type = "time_change"
        await db.add_schedule_change(
            schedule_id, date_str, change_type, new_time=new_value
        )
    else:
        change_type = "room_change"
        await db.add_schedule_change(
            schedule_id, date_str, change_type, new_room=new_value
        )

    await message.answer(
        f"Изменение записано для {args[1]} на {date_str}: {new_value}."
    )


# ═══════════════════════════════════════════════════════
# DEADLINE MANAGEMENT
# ═══════════════════════════════════════════════════════


@router.message(Command("add_deadline"))
@require_role("moderator")
async def cmd_add_deadline(message: types.Message) -> None:
    """Формат: /add_deadline [дата] [название] [описание]"""
    args = (message.text or "").split(None, 3)
    if len(args) < 3:
        await message.answer(
            "Формат: /add_deadline [дата] [название] [описание]\n"
            "Пример: /add_deadline 2025-12-18 Презентация по мифологии Индивидуальная, 6 минут"
        )
        return

    date_str = parse_date(args[1])
    if not date_str:
        await message.answer("Неверный формат даты.")
        return

    title = args[2]
    description = args[3] if len(args) > 3 else ""
    sender = message.from_user.first_name if message.from_user else ""

    dl_id = await db.add_deadline(
        title, date_str, description=description, created_by=sender
    )
    await message.answer(f"Дедлайн добавлен (ID: {dl_id}): {title} до {date_str}.")


@router.message(Command("remove_deadline"))
@require_role("moderator")
async def cmd_remove_deadline(message: types.Message) -> None:
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Формат: /remove_deadline [id]")
        return

    try:
        dl_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    success = await db.remove_deadline(dl_id)
    if success:
        await message.answer(f"Дедлайн {dl_id} удален.")
    else:
        await message.answer("Дедлайн не найден.")


# ═══════════════════════════════════════════════════════
# EXAM MANAGEMENT
# ═══════════════════════════════════════════════════════


@router.message(Command("add_exam"))
@require_role("admin")
async def cmd_add_exam(message: types.Message) -> None:
    """Формат: /add_exam [предмет] [дата] [время] [аудитория] [тип]"""
    args = (message.text or "").split(None, 5)
    if len(args) < 3:
        await message.answer(
            "Формат: /add_exam [предмет] [дата] [время] [аудитория] [тип]\n"
            "Тип: riadny, opravny, druhy_opravny\n"
            "Пример: /add_exam Logika 2026-01-15 10:00 A1 riadny"
        )
        return

    # Найти предмет
    subject = await db.get_subject_by_name(args[1])
    if not subject:
        await message.answer(
            f"Предмет '{args[1]}' не найден в базе. Сначала добавь его через /add_subject."
        )
        return

    date_str = parse_date(args[2])
    if not date_str:
        await message.answer("Неверный формат даты.")
        return

    exam_time = args[3] if len(args) > 3 else ""
    room = args[4] if len(args) > 4 else ""
    exam_type = args[5] if len(args) > 5 else "riadny"

    exam_id = await db.add_exam(subject["id"], date_str, exam_time, room, exam_type)
    await message.answer(
        f"Экзамен добавлен (ID: {exam_id}): {subject['name_ru']} на {date_str}."
    )


# ═══════════════════════════════════════════════════════
# SUBJECT / LINK / NOTE MANAGEMENT
# ═══════════════════════════════════════════════════════


@router.message(Command("add_subject"))
@require_role("admin")
async def cmd_add_subject(message: types.Message) -> None:
    """Формат: /add_subject [название_ru] | [название_sk] | [преподаватель] | [формат_экзамена]"""
    raw = (message.text or "").split(None, 1)
    if len(raw) < 2:
        await message.answer(
            "Формат: /add_subject [название_ru] | [название_sk] | [преподаватель] | [формат_экзамена]\n"
            "Пример: /add_subject Основы логики | Zaklady logiky | Dr. Novak | писемка"
        )
        return

    parts = [p.strip() for p in raw[1].split("|")]

    name_ru = parts[0] if len(parts) > 0 else ""
    name_sk = parts[1] if len(parts) > 1 else ""
    teacher = parts[2] if len(parts) > 2 else ""
    exam_type = parts[3] if len(parts) > 3 else ""

    if not name_ru:
        await message.answer("Укажи хотя бы название предмета.")
        return

    subj_id = await db.add_subject(
        name_ru, name_sk=name_sk, teacher=teacher, exam_type=exam_type
    )
    await message.answer(f"Предмет добавлен (ID: {subj_id}): {name_ru}.")


@router.message(Command("add_link"))
@require_role("moderator")
async def cmd_add_link(message: types.Message) -> None:
    """Формат: /add_link [название] [url] [категория]"""
    args = (message.text or "").split(None, 3)
    if len(args) < 3:
        await message.answer(
            "Формат: /add_link [название] [url] [категория]\n"
            "Пример: /add_link AIS https://ais.unipo.sk university"
        )
        return

    category = args[3] if len(args) > 3 else ""
    sender = message.from_user.first_name if message.from_user else ""

    link_id = await db.add_link(args[1], args[2], category=category, added_by=sender)
    await message.answer(f"Ссылка добавлена (ID: {link_id}): {args[1]}.")


@router.message(Command("add_note"))
@require_role("moderator")
async def cmd_add_note(message: types.Message) -> None:
    """Формат: /add_note [категория] [заголовок] [текст]"""
    args = (message.text or "").split(None, 3)
    if len(args) < 4:
        await message.answer(
            "Формат: /add_note [категория] [заголовок] [текст]\n"
            "Категории: faq, info, guide, link\n"
            "Пример: /add_note faq Как сдать экзамен Зарегистрироваться в AIS и прийти."
        )
        return

    sender = message.from_user.first_name if message.from_user else ""
    note_id = await db.add_note(args[1], args[2], args[3], created_by=sender)
    await message.answer(f"Заметка добавлена (ID: {note_id}): {args[2]}.")


# ═══════════════════════════════════════════════════════
# ANNOUNCE / POLL / ROLES / STATS / BROADCAST
# ═══════════════════════════════════════════════════════


@router.message(Command("announce"))
@require_role("admin")
async def cmd_announce(message: types.Message) -> None:
    """Формат: /announce [текст]"""
    args = (message.text or "").split(None, 1)
    if len(args) < 2:
        await message.answer("Формат: /announce [текст]")
        return

    if settings.group_chat_id == 0:
        await message.answer("GROUP_CHAT_ID не настроен.")
        return

    announcement = f"-- Объявление --\n\n{args[1]}"
    try:
        await message.bot.send_message(settings.group_chat_id, announcement)  # type: ignore[union-attr]
        await message.answer("Объявление отправлено.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.message(Command("poll"))
@require_role("admin")
async def cmd_poll(message: types.Message) -> None:
    """Формат: /poll [вопрос] | [вариант1] | [вариант2] | ..."""
    raw = (message.text or "").split(None, 1)
    if len(raw) < 2:
        await message.answer(
            "Формат: /poll [вопрос] | [вариант1] | [вариант2] | ...\n"
            "Пример: /poll Когда готовиться к экзамену? | Утром | Вечером | Ночью"
        )
        return

    parts = [p.strip() for p in raw[1].split("|")]
    if len(parts) < 3:
        await message.answer("Нужен вопрос и минимум 2 варианта ответа.")
        return

    question = parts[0]
    options = parts[1:]
    user_id = message.from_user.id if message.from_user else 0

    poll_id = await db.create_poll(question, options, user_id)
    poll = await db.get_poll(poll_id)

    if not poll:
        await message.answer("Ошибка создания голосования.")
        return

    text = format_poll(poll)

    # Кнопки для голосования
    buttons = []
    for i, option in enumerate(options):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=option,
                    callback_data=f"poll_vote_{poll_id}_{i}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                text="Закрыть голосование",
                callback_data=f"poll_close_{poll_id}",
            )
        ]
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    target_chat = (
        settings.group_chat_id if settings.group_chat_id != 0 else message.chat.id
    )
    try:
        await message.bot.send_message(target_chat, text, reply_markup=keyboard)  # type: ignore[union-attr]
        if target_chat != message.chat.id:
            await message.answer("Голосование отправлено в группу.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.message(Command("set_role"))
@require_role("admin")
async def cmd_set_role(message: types.Message) -> None:
    """Формат: /set_role [user_id] [роль]"""
    args = (message.text or "").split()
    if len(args) < 3:
        await message.answer(
            "Формат: /set_role [user_id] [роль]\nРоли: student, moderator, admin"
        )
        return

    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("user_id должен быть числом.")
        return

    role = args[2].lower()
    if role not in ("student", "moderator", "admin"):
        await message.answer("Допустимые роли: student, moderator, admin")
        return

    await db.upsert_user(target_id, role=role)
    await message.answer(f"Роль пользователя {target_id} установлена: {role}.")


@router.message(Command("stats"))
@require_role("admin")
async def cmd_stats(message: types.Message) -> None:
    stats = await db.get_usage_stats()
    text = format_stats(stats)
    await message.answer(text)


@router.message(Command("broadcast"))
@require_role("admin")
async def cmd_broadcast(message: types.Message) -> None:
    """Формат: /broadcast [текст]"""
    args = (message.text or "").split(None, 1)
    if len(args) < 2:
        await message.answer("Формат: /broadcast [текст]")
        return

    # Получить всех пользователей
    all_users_db = await db.get_db().execute("SELECT id FROM users")
    all_users = await all_users_db.fetchall()

    sent = 0
    failed = 0
    for row in all_users:
        try:
            await message.bot.send_message(row["id"], args[1])  # type: ignore[union-attr]
            sent += 1
            await asyncio.sleep(0.1)
        except Exception:
            failed += 1

    await message.answer(
        f"Рассылка завершена. Отправлено: {sent}, не доставлено: {failed}."
    )


@router.message(Command("quiet"))
@require_role("admin")
async def cmd_quiet(message: types.Message) -> None:
    """Переключить тихий режим (бот не отвечает на вопросы в группах)."""
    current = await db.get_setting("is_quiet_mode", "off")
    new_val = "on" if current == "off" else "off"
    await db.set_setting("is_quiet_mode", new_val)
    status = "включен" if new_val == "on" else "выключен"
    await message.answer(f"Тихий режим {status}.")


@router.message(Command("data"))
@require_role("admin")
async def cmd_data(message: types.Message) -> None:
    """Экспорт данных в JSON."""
    schedule = await db.get_full_schedule()
    subjects = await db.get_all_subjects()
    deadlines = await db.get_active_deadlines()

    data = {
        "schedule": [dict(r) for r in schedule],
        "subjects": [dict(r) for r in subjects],
        "deadlines": [dict(r) for r in deadlines],
    }

    import json

    json_data = json.dumps(data, indent=2, ensure_ascii=False)

    if len(json_data) > 4000:
        # Send as file if too large
        from aiogram.types import BufferedInputFile

        file = BufferedInputFile(json_data.encode(), filename="bot_data.json")
        await message.answer_document(file, caption="Полный экспорт данных")
    else:
        await message.answer(f"```json\n{json_data}\n```", parse_mode="MarkdownV2")
