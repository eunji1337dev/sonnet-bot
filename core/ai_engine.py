"""
AI Engine 2026 Edition.
Advanced Multi-Model Semantic Router, Tool Calling, Vector RAG Memory, and Fallbacks.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from typing import Any, Dict, List

import structlog

from config import settings
from core.memory import MemoryManager
from core.router import SemanticRouter
from core.tools import ToolRegistry
from core import database as db

log = structlog.get_logger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 15]


class DistributedRateLimiter:
    """Enterprise Rate Limiter (Redis-ready with local fallback)."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        
        # Redis client mock/stub for now — ideally Upstash Redis
        self._redis = None
        if os.environ.get("REDIS_URL"):
            try:
                from redis.asyncio import Redis
                self._redis = Redis.from_url(os.environ["REDIS_URL"])
                log.info("Redis rate limiter attached")
            except ImportError:
                pass
        
        # Local fallback if Redis is unavailable
        self._timestamps: Dict[int, deque[float]] = defaultdict(deque)

    async def allow(self, key: int) -> bool:
        if self._redis:
            try:
                # Basic slide-window via Redis INCR / EXPIRE could go here
                # Simplified for demonstration
                current = int(time.time() / self._window)
                redis_key = f"rate:{key}:{current}"
                count = await self._redis.incr(redis_key)
                if count == 1:
                    await self._redis.expire(redis_key, self._window)
                return count <= self._max
            except Exception as e:
                log.warning("redis rate limiter failed, falling back to local", error=str(e))
                self._redis = None

        now = time.monotonic()
        q = self._timestamps[key]
        while q and now - q[0] > self._window:
            q.popleft()
        if len(q) >= self._max:
            return False
        q.append(now)
        return True


class AIEngine:
    """Enterprise Router Engine."""

    def __init__(self) -> None:
        self._init_groq()
        self._init_gemini()

        self._system_prompt = self._load_system_prompt()
        self.memory = MemoryManager()
        self.router = SemanticRouter()
        self.tools = ToolRegistry()
        
        self._global_limiter = DistributedRateLimiter(settings.global_rate_limit, 60)
        self._user_limiters = DistributedRateLimiter(settings.user_rate_limit, 60)
        
        log.info("Enterprise AI engine 2026 initialized")

    def _init_groq(self) -> None:
        from groq import AsyncGroq
        self._groq_client = AsyncGroq(api_key=settings.groq_key.get_secret_value())

    def _init_gemini(self) -> None:
        from google import genai
        self._gemini_client = genai.Client(api_key=settings.gemini_key.get_secret_value())

    @staticmethod
    def _load_file(filename: str, fallback: str = "") -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", filename
        )
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return fallback

    def _load_system_prompt(self) -> str:
        return self._load_file(
            "system_prompt.txt",
            "You are Sonnet. Answer concisely.",
        )

    # ═══════════════════════════════════════════════════════
    # EXECUTION PATHS
    # ═══════════════════════════════════════════════════════

    async def _call_groq(self, message: str, full_system: str) -> str:
        """Fast path for simple chat using Groq."""
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",  # Extremely fast
                    messages=[
                        {"role": "system", "content": full_system},
                        {"role": "user", "content": message},
                    ],
                    max_tokens=1024,
                    temperature=0.7,
                )
                return response.choices[0].message.content or "No response"
            except Exception as e:
                log.warning("Groq fallback", error=str(e), attempt=attempt)
                await asyncio.sleep(_RETRY_DELAYS[attempt])
        return "⚠️ Groq backend error."

    async def _call_gemini_with_tools(self, message: str, full_system: str, max_turns: int = 5) -> str:
        """Slower, deeper conceptual path with Tool Use via Gemini 2.0 Pro."""
        from google.genai import types
        
        chat = self._gemini_client.chats.create(
            model="gemini-2.5-pro", # Use the best Gemini model available
            config=types.GenerateContentConfig(
                system_instruction=full_system,
                tools=self.tools.gemini_tools,
                temperature=0.4,
            )
        )
        
        # We simulate a "turn" loop to allow the LLM to call tools -> get response -> answer
        current_message = message
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=message)])]
        
        for turn in range(max_turns):
            response = await asyncio.to_thread(
                chat.send_message,
                contents
            )
            
            # Check if LLM requested a function call
            if response.function_calls:
                function_responses = []
                for call in response.function_calls:
                    tool_result = await self.tools.execute_tool(call)
                    function_responses.append(tool_result)
                
                # Append tool responses back into the history for the LLM
                contents = [types.Content(role="function", parts=function_responses)]
                continue # Let LLM reason over the generic JSON data
                
            # If no function call, it's the final text response
            return response.text or "No response from Gemini"
            
        return "⚠️ Tool loop exceeded max turns."

    # ═══════════════════════════════════════════════════════
    # ОСНОВНОЙ МЕТОД
    # ═══════════════════════════════════════════════════════

    async def generate_response(
        self,
        user_id: int,
        message: str,
        db_context: str = "",
        sender_name: str = "",
        chat_history: str = "", # Ignored, replaced by RAG
    ) -> str:
        """Multi-model generative entrypoint."""

        if not await self._user_limiters.allow(user_id):
            return "⏳ Слишком много запросов. Подожди минуту."
        if not await self._global_limiter.allow(0):
            return "⏳ Очередь AI-модуля переполнена."

        # 1. RAG: Retrieve Semantic Memory
        rag_context = await self.memory.semantic_search(user_id, message)
        
        # Assemble System Prompt
        parts = [self._system_prompt]
        if rag_context:
            parts.append(f"=== PAST MEMORY CONTEXT (RAG) ===\n{rag_context}")
        if sender_name:
            parts.append(f"User Name: {sender_name}")
            
        full_system = "\n\n".join(parts)
        
        # 2. Semantic Routing
        start = time.monotonic()
        intent = await self.router.classify_intent(message)
        
        # 3. Execution
        try:
            if intent.needs_tools:
                log.info("Routing to Gemini (Tool Use)", intent=intent.intent_type)
                answer = await self._call_gemini_with_tools(message, full_system)
            else:
                log.info("Routing to Groq (Fast Chat)", intent=intent.intent_type)
                answer = await self._call_groq(message, full_system)
        except Exception as e:
            log.error("AI Routing execution failed completely", error=str(e))
            answer = "Произошла архитектурная ошибка при генерации ответа."

        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info("Response generated", user_id=user_id, elapsed_ms=elapsed_ms, tools=intent.needs_tools)
        
        # 4. Long Term Memory Save
        if len(answer) > 5 and len(message) > 5 and not answer.startswith("⏳"):
            await self.memory.add_chat_message(user_id, message, "user")
            await self.memory.add_chat_message(user_id, answer, "assistant")
            
        return answer

    def clear_context(self, user_id: int) -> None:
        pass # Not applicable in 2026 stateless RAG design


GeminiEngine = AIEngine


def split_long_message(text: str, max_length: int = 4096) -> List[str]:
    """Split long messages."""
    if len(text) <= max_length:
        return [text]

    parts: List[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        if not current:
            current = paragraph
        elif len(current) + 2 + len(paragraph) <= max_length:
            current += "\n\n" + paragraph
        else:
            parts.append(current.strip())
            current = paragraph

    if current.strip():
        if len(current) > max_length:
            lines = current.split("\n")
            chunk = ""
            for line in lines:
                if len(chunk) + 1 + len(line) <= max_length:
                    chunk += ("\n" + line) if chunk else line
                else:
                    if chunk:
                        parts.append(chunk.strip())
                    chunk = line
            if chunk:
                parts.append(chunk.strip())
        else:
            parts.append(current.strip())

    return parts if parts else [text[:max_length]]
