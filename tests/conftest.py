import pytest_asyncio
import aiosqlite
from unittest.mock import patch

import core.database as db


@pytest_asyncio.fixture(autouse=True)
async def mock_db():
    """Перенаправляем все вызовы БД на in-memory SQLite (для тестов)."""
    # Create in-memory db
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    # Stub the get_db inside our mocked core to return this in-memory conn
    with patch("core.database.get_db", return_value=conn):
        # Initialize the schema
        await db._create_tables()
        yield conn

    await conn.close()
