"""
Модуль статистики.
"""

from __future__ import annotations

from typing import Dict, Any

from core import database as db


async def get_bot_stats(days: int = 7) -> Dict[str, Any]:
    """Получить полную статистику бота."""
    return await db.get_usage_stats(days)
