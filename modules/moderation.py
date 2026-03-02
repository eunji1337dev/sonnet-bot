"""
Модуль модерации.
Антиспам, приветствие новых участников, тихий режим.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Optional

import structlog
from aiogram import Bot, Router, types
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION

from config import settings

log = structlog.get_logger(__name__)

router = Router(name="moderation")

# Антиспам трекер: user_id -> deque[timestamp]
_spam_tracker: dict[int, deque[float]] = defaultdict(
    lambda: deque(maxlen=settings.spam_msg_count + 1)
)
_muted_until: dict[int, float] = {}

# Тихий режим (глобальный)
_quiet_mode: bool = False


def is_quiet_mode() -> bool:
    return _quiet_mode


def set_quiet_mode(enabled: bool) -> None:
    global _quiet_mode
    _quiet_mode = enabled


def check_spam(user_id: int) -> bool:
    """Проверить, спамит ли пользователь. Возвращает True если спам обнаружен."""
    now = time.monotonic()

    # Если в муте — продолжаем блокировать
    if user_id in _muted_until:
        if now < _muted_until[user_id]:
            return True
        else:
            del _muted_until[user_id]

    tracker = _spam_tracker[user_id]
    tracker.append(now)

    if len(tracker) >= settings.spam_msg_count:
        oldest = tracker[0]
        if now - oldest < settings.spam_window_sec:
            # Слишком много сообщений — мут на 5 минут
            _muted_until[user_id] = now + 300
            log.warning("spam detected, user muted", user_id=user_id)
            return True

    return False


# ═══════════════════════════════════════════════════════
# WELCOME NEW MEMBERS
# ═══════════════════════════════════════════════════════


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def handle_new_member(event: types.ChatMemberUpdated) -> None:
    """Приветствие нового участника."""
    if event.chat.id != settings.group_chat_id and settings.group_chat_id != 0:
        return

    new_member = event.new_chat_member.user
    name = new_member.first_name or "участник"

    text = (
        f"Добро пожаловать в группу Europske studia, {name}.\n"
        "Я Sonnet — AI-ассистент группы. Напиши /start чтобы узнать о моих возможностях, "
        "или задай мне любой вопрос."
    )

    try:
        bot: Optional[Bot] = event.bot  # type: ignore[assignment]
        if bot:
            await bot.send_message(event.chat.id, text)
    except Exception as e:
        log.error("failed to welcome new member", error=str(e))
