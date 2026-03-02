import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from handlers.messages import handle_ai_message
from handlers.admin import cmd_quiet
from handlers.commands import cmd_subject


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.generate_response = AsyncMock(return_value="Test Answer")
    return engine


@pytest.fixture
def mock_message():
    message = MagicMock()
    message.text = "Hello?"
    message.chat = MagicMock()
    message.chat.id = 123
    message.chat.type = "private"
    message.from_user = MagicMock()
    message.from_user.id = 456
    message.from_user.username = "testuser"
    message.reply = AsyncMock()
    message.bot = MagicMock()
    message.bot.send_chat_action = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_handle_ai_message_private_chat(mock_message, mock_engine):
    with (
        patch("handlers.messages._engine", mock_engine),
        patch(
            "handlers.messages._build_message_context",
            AsyncMock(return_value="Context"),
        ),
        patch("core.database.get_setting", AsyncMock(return_value="off")),
    ):
        await handle_ai_message(mock_message)

        mock_message.reply.assert_called_once()
        assert "Test Answer" in mock_message.reply.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_ai_message_respects_quiet_mode_in_group(
    mock_message, mock_engine
):
    mock_message.chat.type = "group"

    with (
        patch("handlers.messages._engine", mock_engine),
        patch("core.database.get_setting", AsyncMock(return_value="on")),
    ):
        await handle_ai_message(mock_message)

        # Should NOT reply in group if quiet mode is ON
        mock_message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_quiet_toggles(mock_message):
    mock_message.answer = AsyncMock()
    with (
        patch("utils.permissions.check_permission", AsyncMock(return_value=True)),
        patch("core.database.get_setting", AsyncMock(return_value="off")),
        patch("core.database.set_setting", AsyncMock()) as mock_set,
    ):
        await cmd_quiet(mock_message)
        mock_set.assert_called_with("is_quiet_mode", "on")
        mock_message.answer.assert_called()


@pytest.mark.asyncio
async def test_handle_subject_found(mock_message):
    mock_message.text = "/subject Geography"
    mock_message.answer = AsyncMock()
    mock_subject = {"name_ru": "География", "teacher": "Teacher", "exam_type": "Exam"}

    with patch(
        "core.database.get_subject_by_name", AsyncMock(return_value=mock_subject)
    ):
        await cmd_subject(mock_message)
        mock_message.answer.assert_called()
        assert "География" in mock_message.answer.call_args[0][0]
