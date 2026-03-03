from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import structlog
from groq import AsyncGroq

from config import settings

log = structlog.get_logger(__name__)


@dataclass
class Intent:
    needs_tools: bool
    intent_type: str
    confidence: float


class SemanticRouter:
    """Fast semantic router using Groq Llama to classify user intents."""

    def __init__(self) -> None:
        self._client = AsyncGroq(api_key=settings.groq_key.get_secret_value())
        # We use a fast, reasoning-capable model for classification
        self._model = "llama-3.1-8b-instant"
        
        self._router_prompt = """
You are a Semantic Router for a University Student Assistant Bot.
Classify the user's input into exactly ONE of the following precise intent categories:

1. "SCHEDULE_QUERY": ASKING for the schedule, timetable, next class, or upcoming classes today/tomorrow/specifc day.
2. "DEADLINE_QUERY": ASKING for homework deadlines, exams, tests, or submissions.
3. "DB_QUERY": Asking for subjects info, teachers, links, or FAQ notes stored in the database.
4. "REMINDER_CREATE": Asking to set a reminder or alarm.
5. "GENERAL_CHAT": Basic conversation, casual talk, translations, general knowledge questions, or ANY other query that DOES NOT require querying the university database.

Respond in strict JSON format:
{
  "intent_category": "CATEGORY_NAME_HERE",
  "confidence": 0.95
}
"""

    async def classify_intent(self, message: str) -> Intent:
        """Determines if the message requires heavy tool usage or just fast chat."""
        if len(message.strip()) < 3:
            return Intent(needs_tools=False, intent_type="GENERAL_CHAT", confidence=1.0)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._router_prompt},
                    {"role": "user", "content": message},
                ],
                response_format={"type": "json_object"},
                max_tokens=64,
                temperature=0.0,
            )
            
            content = response.choices[0].message.content
            if not content:
                 return Intent(needs_tools=False, intent_type="GENERAL_CHAT", confidence=0.0)
                 
            data = json.loads(content)
            intent_type = data.get("intent_category", "GENERAL_CHAT")
            confidence = float(data.get("confidence", 0.0))
            
            # Tools are needed for everything EXCEPT general chat
            needs_tools = intent_type != "GENERAL_CHAT"
            
            log.info("semantic router classified", intent=intent_type, tools=needs_tools)
            return Intent(needs_tools=needs_tools, intent_type=intent_type, confidence=confidence)

        except Exception as e:
            log.error("semantic router failed, defaulting to general chat", error=str(e))
            # Fallback to general chat if router fails to avoid halting
            return Intent(needs_tools=False, intent_type="GENERAL_CHAT", confidence=0.0)
