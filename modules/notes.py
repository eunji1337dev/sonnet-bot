"""
Модуль заметок и ссылок.
"""

from __future__ import annotations

from core import database as db


async def add_note_entry(
    category: str, title: str, content: str, tags: str = "", created_by: str = ""
) -> int:
    return await db.add_note(category, title, content, tags, created_by)


async def add_link_entry(
    title: str, url: str, category: str = "", description: str = "", added_by: str = ""
) -> int:
    return await db.add_link(title, url, category, description, added_by)


async def search_notes_by_query(query: str):
    return await db.search_notes(query)
