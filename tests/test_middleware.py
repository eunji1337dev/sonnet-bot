import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from handlers.middleware import (
    UserTrackingMiddleware,
    PrivateMessageFilterMiddleware,
    AntiSpamMiddleware,
)

from aiogram.types import Message, Chat, User


@pytest.mark.asyncio
async def test_user_tracking_middleware_upserts_user():
    middleware = UserTrackingMiddleware()
    handler = AsyncMock(return_value="OK")

    # Use spec=Message to satisfy isinstance checks
    event = MagicMock(spec=Message)
    event.from_user = MagicMock(spec=User)
    event.from_user.id = 123
    event.from_user.username = "testuser"
    event.from_user.first_name = "Ivan"
    event.from_user.last_name = "Ivanov"

    with patch("core.database.upsert_user", AsyncMock()) as mock_upsert:
        await middleware(handler, event, {"data": 1})
        mock_upsert.assert_called_with(
            user_id=123, username="testuser", first_name="Ivan", last_name="Ivanov"
        )
        handler.assert_called_once()


@pytest.mark.asyncio
async def test_private_message_filter_blocks_unknown_user():
    middleware = PrivateMessageFilterMiddleware()
    handler = AsyncMock()

    event = MagicMock(spec=Message)
    event.chat = MagicMock(spec=Chat)
    event.chat.type = "private"
    event.chat.id = 12345
    event.from_user = MagicMock(spec=User)
    event.from_user.id = 777
    event.from_user.username = "random_guy"
    event.answer = AsyncMock()

    await middleware(handler, event, {})
    handler.assert_not_called()
    event.answer.assert_called()


@pytest.mark.asyncio
async def test_antispam_middleware_mutes_after_limit():
    # Limit 2 messages: 3rd should block
    middleware = AntiSpamMiddleware(limit=2, window=10, mute_time=60)
    handler = AsyncMock(return_value="OK")

    event = MagicMock(spec=Message)
    event.from_user = MagicMock(spec=User)
    event.from_user.id = 999
    event.reply = AsyncMock()

    # 1st message - PASS
    await middleware(handler, event, {})
    # 2nd message - PASS
    await middleware(handler, event, {})
    # 3rd message - BLOCK
    res = await middleware(handler, event, {})

    assert res is None
    # Check if reply was called (middleware sends a warning)
    event.reply.assert_called()
