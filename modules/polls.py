"""
Модуль голосований.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from core import database as db


async def create_new_poll(question: str, options: List[str], created_by: int) -> int:
    """Создать голосование."""
    return await db.create_poll(question, options, created_by)


async def vote(poll_id: int, user_id: int, option_index: int) -> bool:
    """Проголосовать."""
    return await db.vote_poll(poll_id, user_id, option_index)


async def close(poll_id: int) -> bool:
    """Закрыть голосование."""
    return await db.close_poll(poll_id)


async def get_poll_data(poll_id: int) -> Optional[Dict[str, Any]]:
    """Получить данные голосования."""
    return await db.get_poll(poll_id)
