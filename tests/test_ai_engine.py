import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from core.ai_engine import AIEngine

@pytest.fixture
def mock_dependencies():
    with patch("core.ai_engine.MemoryManager") as mock_memory, \
         patch("core.ai_engine.SemanticRouter") as mock_router, \
         patch("core.ai_engine.ToolRegistry") as mock_tools:
        
        mock_router_instance = mock_router.return_value
        mock_intent = MagicMock()
        mock_intent.needs_tools = False
        mock_intent.intent_type = "GENERAL_CHAT"
        mock_router_instance.classify_intent = AsyncMock(return_value=mock_intent)
        
        mock_memory_instance = mock_memory.return_value
        mock_memory_instance.semantic_search = AsyncMock(return_value="rag context")
        mock_memory_instance.add_chat_message = AsyncMock()
        
        yield {
            "memory": mock_memory_instance,
            "router": mock_router_instance,
            "intent": mock_intent
        }


@pytest.mark.asyncio
async def test_ai_generate_response_routing_to_groq(mock_dependencies):
    with patch("core.ai_engine.AIEngine._init_groq"), \
         patch("core.ai_engine.AIEngine._init_gemini"):
             
        engine = AIEngine()
        # Mock rate limiters
        engine._user_limiters.allow = AsyncMock(return_value=True)
        engine._global_limiters = AsyncMock()
        engine._global_limiter.allow = AsyncMock(return_value=True)
        
        engine._call_groq = AsyncMock(return_value="Groq Answer")
        
        response = await engine.generate_response(1, "Hello")
        
        assert response == "Groq Answer"
        engine.router.classify_intent.assert_called_once_with("Hello")
        engine._call_groq.assert_called_once()


@pytest.mark.asyncio
async def test_ai_generate_response_routing_to_gemini(mock_dependencies):
    mock_dependencies["intent"].needs_tools = True
    
    with patch("core.ai_engine.AIEngine._init_groq"), \
         patch("core.ai_engine.AIEngine._init_gemini"):
             
        engine = AIEngine()
        engine._user_limiters.allow = AsyncMock(return_value=True)
        engine._global_limiter.allow = AsyncMock(return_value=True)
        
        engine._call_gemini_with_tools = AsyncMock(return_value="Gemini Answer")
        
        response = await engine.generate_response(1, "What is the schedule?")
        
        assert response == "Gemini Answer"
        engine._call_gemini_with_tools.assert_called_once()
