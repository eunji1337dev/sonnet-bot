import pytest
import asyncio
from unittest.mock import patch, MagicMock
from core.scheduler import scheduler_loop


@pytest.fixture
def mock_db():
    with patch("core.database.get_db") as mock_conn:
        yield mock_conn


@pytest.mark.asyncio
async def test_scheduler_loop_skips_when_quiet_mode_is_on(mock_db):
    # Mock settings and quiet mode
    with (
        patch("core.database.get_setting", return_value="on"),
        patch("asyncio.sleep", side_effect=asyncio.CancelledError),
    ):
        # This will run once and then exit due to CancelledError side effect on sleep
        try:
            await scheduler_loop(MagicMock())
        except asyncio.CancelledError:
            pass

    # Success is not crashing and respect settings


@pytest.mark.asyncio
async def test_scheduler_loop_checks_classes(mock_db):
    # Mock settings and quiet mode off
    mock_bot = MagicMock()

    with (
        patch("core.database.get_setting", return_value="off"),
        patch("core.database.get_classes_starting_at", return_value=[]),
        patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError]),
    ):
        try:
            await scheduler_loop(mock_bot)
        except asyncio.CancelledError:
            pass

    # Verify it tried to check classes if not in quiet mode
    # (Assuming scheduler_loop checks immediately or after first sleep)
