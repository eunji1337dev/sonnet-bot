"""
Модуль FAQ.
"""

from __future__ import annotations

from typing import List, Dict, Any

from core import database as db


async def get_faq_list() -> List[Dict[str, Any]]:
    """Получить все FAQ-записи."""
    return await db.get_notes_by_category("faq")


async def search_faq(query: str) -> List[Dict[str, Any]]:
    """Поиск по FAQ."""
    all_faq = await db.get_notes_by_category("faq")
    query_lower = query.lower()
    return [
        f
        for f in all_faq
        if query_lower in f["title"].lower()
        or query_lower in f["content"].lower()
        or query_lower in (f.get("tags") or "").lower()
    ]
