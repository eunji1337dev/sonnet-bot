"""
Обработка inline-кнопок (callback queries).
Навигация /start меню, /admin панель, голосования, пагинация.
"""

from __future__ import annotations

import structlog
from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import database as db
from utils.formatters import (
    format_deadlines,
    format_exams,
    format_faq,
    format_links,
    format_poll,
    format_stats,
)
from utils.permissions import check_permission
from modules.subjects import get_subjects_list_text
from modules.schedule import get_today_schedule_text

log = structlog.get_logger(__name__)

router = Router(name="callbacks")


# ═══════════════════════════════════════════════════════
# START MENU
# ═══════════════════════════════════════════════════════


@router.callback_query(lambda c: c.data and c.data.startswith("menu_"))
async def handle_menu_callback(callback: types.CallbackQuery) -> None:
    action = callback.data.replace("menu_", "")  # type: ignore[union-attr]

    if action == "schedule":
        text = await get_today_schedule_text()
    elif action == "exams":
        exams = await db.get_upcoming_exams(90)
        text = format_exams(exams)
    elif action == "deadlines":
        deadlines = await db.get_active_deadlines()
        text = format_deadlines(deadlines)
    elif action == "subjects":
        text = await get_subjects_list_text()
    elif action == "links":
        links = await db.get_all_links()
        text = format_links(links)
    elif action == "faq":
        notes = await db.get_notes_by_category("faq")
        text = format_faq(notes)
    elif action == "help":
        from handlers.commands import HELP_TEXT

        text = HELP_TEXT
    else:
        text = "Неизвестный раздел."

    back_button = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="< Назад", callback_data="menu_back")]
        ]
    )

    try:
        await callback.message.edit_text(text, reply_markup=back_button)  # type: ignore[union-attr]
    except TelegramBadRequest:
        pass  # Сообщение уже содержит этот текст
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu_back")
async def handle_menu_back(callback: types.CallbackQuery) -> None:
    text = (
        "Sonnet — AI-ассистент группы Europske studia.\n\n"
        'Выбери раздел или напиши "Sonnet, ..." чтобы задать вопрос.'
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

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)  # type: ignore[union-attr]
    except TelegramBadRequest:
        pass  # Сообщение уже содержит этот текст
    await callback.answer()


# ═══════════════════════════════════════════════════════
# ADMIN PANEL
# ═══════════════════════════════════════════════════════


@router.callback_query(lambda c: c.data and c.data.startswith("admin_"))
async def handle_admin_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    if not await check_permission(user_id, "admin"):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    action = callback.data.replace("admin_", "")  # type: ignore[union-attr]

    if action == "stats":
        stats = await db.get_usage_stats()
        text = format_stats(stats)
    elif action == "back":
        text = "Панель администратора"
        keyboard = _admin_keyboard()
        await callback.message.edit_text(text, reply_markup=keyboard)  # type: ignore[union-attr]
        await callback.answer()
        return
    else:
        text = "Используй команды для управления: /add_class, /add_deadline, /add_exam, /add_link, /add_note"

    back_button = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="< Назад", callback_data="admin_back")]
        ]
    )

    await callback.message.edit_text(text, reply_markup=back_button)  # type: ignore[union-attr]
    await callback.answer()


def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="Управление", callback_data="admin_manage")],
        ]
    )


# ═══════════════════════════════════════════════════════
# POLL VOTES
# ═══════════════════════════════════════════════════════


@router.callback_query(lambda c: c.data and c.data.startswith("poll_vote_"))
async def handle_poll_vote(callback: types.CallbackQuery) -> None:
    # poll_vote_<poll_id>_<option_index>
    parts = callback.data.split("_")  # type: ignore[union-attr]
    if len(parts) < 4:
        await callback.answer("Ошибка голосования.", show_alert=True)
        return

    try:
        poll_id = int(parts[2])
        option_index = int(parts[3])
    except ValueError:
        await callback.answer("Ошибка голосования.", show_alert=True)
        return

    success = await db.vote_poll(poll_id, callback.from_user.id, option_index)
    if not success:
        await callback.answer(
            "Не удалось проголосовать. Возможно, голосование закрыто.", show_alert=True
        )
        return

    # Обновить сообщение с результатами
    poll = await db.get_poll(poll_id)
    if poll:
        text = format_poll(poll)
        keyboard = _poll_keyboard(poll_id, poll["options"], poll["is_active"])
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)  # type: ignore[union-attr]
        except Exception as e:
            structlog.get_logger(__name__).debug(
                "Callback message edit failed", error=str(e)
            )

    await callback.answer("Голос принят.")


@router.callback_query(lambda c: c.data and c.data.startswith("poll_close_"))
async def handle_poll_close(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    if not await check_permission(user_id, "admin"):
        await callback.answer(
            "Только администратор может закрыть голосование.", show_alert=True
        )
        return

    try:
        poll_id = int(callback.data.split("_")[2])  # type: ignore[union-attr]
    except (ValueError, IndexError):
        await callback.answer("Ошибка.", show_alert=True)
        return

    await db.close_poll(poll_id)
    poll = await db.get_poll(poll_id)
    if poll:
        text = format_poll(poll)
        await callback.message.edit_text(text)  # type: ignore[union-attr]

    await callback.answer("Голосование закрыто.")


def _poll_keyboard(
    poll_id: int, options: list, is_active: bool
) -> InlineKeyboardMarkup:
    if not is_active:
        return InlineKeyboardMarkup(inline_keyboard=[])

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

    return InlineKeyboardMarkup(inline_keyboard=buttons)
