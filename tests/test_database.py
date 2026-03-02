import pytest
from core.database import (
    _seed_schedule,
    _seed_subjects,
    _SCHEDULE_SEED,
    _SUBJECTS_SEED,
    get_setting,
    set_setting,
    upsert_user,
    get_user_role,
    set_user_role,
    add_note,
    get_notes_by_category,
)


@pytest.mark.asyncio
async def test_database_seeding_loads_correct_counts(mock_db):
    """Убедимся, что seed функции корректно загружают начальные данные."""
    await _seed_subjects()
    await _seed_schedule()

    cursor = await mock_db.execute("SELECT COUNT(*) FROM subjects")
    row = await cursor.fetchone()
    assert row[0] == len(_SUBJECTS_SEED)

    cursor = await mock_db.execute("SELECT COUNT(*) FROM schedule")
    row = await cursor.fetchone()
    assert row[0] == len(_SCHEDULE_SEED)


@pytest.mark.asyncio
async def test_settings_crud(mock_db):
    """Проверка сохранения и получения настроек."""
    await set_setting("test_key", "test_value")
    val = await get_setting("test_key")
    assert val == "test_value"

    # Default value
    assert await get_setting("missing", "default") == "default"


@pytest.mark.asyncio
async def test_users_crud(mock_db):
    """Проверка работы с пользователями."""
    await upsert_user(123, "testuser", "Ivan", "Ivanov", "student")
    role = await get_user_role(123)
    assert role == "student"

    await set_user_role(123, "admin")
    role = await get_user_role(123)
    assert role == "admin"


@pytest.mark.asyncio
async def test_notes_crud(mock_db):
    """Проверка создания и получения заметок."""
    await add_note("test_cat", "Title", "Content", "tags", "creator")
    notes = await get_notes_by_category("test_cat")
    assert len(notes) == 1
    assert notes[0]["title"] == "Title"
    assert notes[0]["content"] == "Content"
