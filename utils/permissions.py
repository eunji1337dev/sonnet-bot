"""
Проверка прав доступа пользователей.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable

import structlog
from aiogram import types

from config import settings
from core import database as db

log = structlog.get_logger(__name__)


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором по конфигу."""
    return user_id in settings.admin_id_list


async def get_effective_role(user_id: int) -> str:
    """Получить эффективную роль пользователя (из БД или конфига)."""
    if is_admin(user_id):
        return "admin"
    return await db.get_user_role(user_id)


async def check_permission(user_id: int, required_role: str) -> bool:
    """Проверить, имеет ли пользователь указанную роль или выше."""
    role_hierarchy = {"student": 0, "moderator": 1, "admin": 2}
    user_role = await get_effective_role(user_id)
    return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)


def require_role(role: str):
    """Декоратор для ограничения доступа к хендлерам по роли."""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(message: types.Message, *args, **kwargs):
            user_id = message.from_user.id if message.from_user else 0
            if not await check_permission(user_id, role):
                await message.reply("У тебя нет прав для выполнения этой команды.")
                return
            return await func(message, *args, **kwargs)

        return wrapper

    return decorator
