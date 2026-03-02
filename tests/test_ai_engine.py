import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from core.ai_engine import GeminiEngine


@pytest.fixture
def mock_groq():
    """Mock Groq client."""
    with patch("groq.Groq") as MockGroq:
        mock_client = MockGroq.return_value
        yield mock_client


@pytest.fixture
def mock_gemini():
    """Mock Gemini client."""
    with patch("google.genai.Client") as mock_gemini_client:
        yield mock_gemini_client


@pytest.mark.asyncio
async def test_ai_engine_initializes_with_correct_model(mock_groq, mock_gemini):
    with patch("config.settings.ai_provider", "groq"):
        engine = GeminiEngine()
        assert engine._provider == "groq"


@pytest.mark.asyncio
async def test_ai_generate_response_uses_groq(mock_groq, mock_gemini):
    with patch("config.settings.ai_provider", "groq"):
        engine = GeminiEngine()

        # Configure the mock chain: client.chat.completions.create().choices[0].message.content
        from unittest.mock import MagicMock

        mock_choice = MagicMock()
        mock_choice.message.content = "Test Groq Response"
        mock_groq.chat.completions.create.return_value.choices = [mock_choice]

        # Override _call_groq to not run in a separate thread for testing, or just mock the inner behavior.
        # It's better to patch the internal asyncio.to_thread if we test threading,
        # but here the mock is standard synchronous MagicMock, so `to_thread` will resolve it seamlessly.
        resp = await engine.generate_response(user_id=1, message="Hello")
        assert resp == "Test Groq Response"
        mock_groq.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_ai_generate_response_retries_on_error(mock_groq, mock_gemini):
    with patch("config.settings.ai_provider", "groq"):
        engine = GeminiEngine()

        # Mock failure then success
        mock_choice = MagicMock()
        mock_choice.message.content = "Success After Retry"

        # ERROR STRING MUST CONTAIN "429" OR "rate" to trigger retry in ai_engine.py
        mock_groq.chat.completions.create.side_effect = [
            Exception("429 Rate limit"),
            MagicMock(choices=[mock_choice]),
        ]

        # We need to patch time.sleep or similar if there was a delay,
        # but GeminiEngine uses exponential backoff.
        # Let's assume it works or mock the sleep.
        with patch("asyncio.sleep", AsyncMock()):
            resp = await engine.generate_response(user_id=1, message="Hello")
            assert resp == "Success After Retry"
            assert mock_groq.chat.completions.create.call_count == 2
