"""
Middleware для Sonnet: логирование, отслеживание пользователей.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

import structlog
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from core import database as db
from config import settings

log = structlog.get_logger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Логирование каждого входящего update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text:
            log.info(
                "incoming message",
                user_id=event.from_user.id if event.from_user else 0,
                username=event.from_user.username if event.from_user else "",
                chat_id=event.chat.id,
                chat_type=event.chat.type,
                text=event.text[:80],
            )
        elif isinstance(event, CallbackQuery):
            log.info(
                "incoming callback",
                user_id=event.from_user.id if event.from_user else 0,
                data=event.data,
            )
        return await handler(event, data)


class UserTrackingMiddleware(BaseMiddleware):
    """Auto-upsert пользователя при каждом сообщении."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            user = event.from_user
            try:
                await db.upsert_user(
                    user_id=user.id,
                    username=user.username or "",
                    first_name=user.first_name or "",
                    last_name=user.last_name or "",
                )
            except Exception as e:
                structlog.get_logger(__name__).debug(
                    "Logging middleware failed", error=str(e)
                )
        return await handler(event, data)


class PrivateMessageFilterMiddleware(BaseMiddleware):
    """
    Блокировка ЛС для всех, кроме разрешенных пользователей.
    Разрешены только @derontavicious и @widzzzo.
    """

    ALLOWED_USERNAMES = {"derontavicious", "widzzzo"}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:

        # Проверяем только Message и CallbackQuery, которые имеют отношение к чату
        chat = None
        user = None

        if isinstance(event, Message):
            chat = event.chat
            user = event.from_user
        elif isinstance(event, CallbackQuery) and event.message:
            chat = getattr(event.message, "chat", None)
            user = event.from_user

        if chat and chat.type == "private" and user:
            username = (user.username or "").lower()
            if username not in self.ALLOWED_USERNAMES:
                log.info("private message blocked", user_id=user.id, username=username)

                # Сообщаем пользователю, что доступ закрыт
                if isinstance(event, Message):
                    try:
                        await event.answer(
                            "🛑 <b>Доступ запрещен</b>\n\n"
                            "Из-за действующих ограничений API я не могу общаться в личных сообщениях со всеми пользователями.\n\n"
                            "Пожалуйста, используй меня в нашей общей группе.\n"
                            "Если тебе очень нужен доступ в ЛС, напиши <b>@derontavicious</b>.",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        log.error("failed to send block message", error=str(e))

                return  # Полностью дропаем апдейт

        return await handler(event, data)


class AntiSpamMiddleware(BaseMiddleware):
    """
    Глобальный антиспам фильтр.
    Отбрасывает сообщения от пользователей, отправляющих слишком много запросов
    за короткий промежуток времени.
    """

    def __init__(
        self,
        limit: int = settings.spam_msg_count,
        window: int = settings.spam_window_sec,
        mute_time: int = 300,
    ) -> None:
        from collections import defaultdict, deque

        super().__init__()
        self.limit = limit
        self.window = window
        self.mute_time = mute_time

        # user_id -> deque[timestamp]
        self._spam_tracker: Dict[int, deque[float]] = defaultdict(
            lambda: deque(maxlen=limit + 1)
        )
        # user_id -> timestamp until muted
        self._muted_until: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Применяем антиспам только для пользователей
        if not hasattr(event, "from_user") or not event.from_user:
            return await handler(event, data)

        import time

        now = time.monotonic()
        user_id = event.from_user.id

        # Проверка мута
        if user_id in self._muted_until:
            if now < self._muted_until[user_id]:
                # Отбрасываем update
                log.info("antispam: update dropped for muted user", user_id=user_id)
                return None
            else:
                del self._muted_until[user_id]

        # Логика трекинга
        tracker = self._spam_tracker[user_id]
        tracker.append(now)

        if len(tracker) >= self.limit:
            oldest = tracker[0]
            if now - oldest < self.window:
                self._muted_until[user_id] = now + self.mute_time
                log.warning("antispam: user muted", user_id=user_id, window=self.window)

                # Попробуем отправить алерт пользователю один раз
                if isinstance(event, Message):
                    try:
                        await event.reply(
                            "🚫 <b>Вы отправляете слишком много запросов.</b>\n"
                            f"Пожалуйста, подождите {self.mute_time} секунд.",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        log.error("antispam: failed to send warning", error=str(e))
                return None

        # Пропускаем дальше
        return await handler(event, data)
