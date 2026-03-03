"""
AI Engine — поддержка Groq (Llama) и Gemini.
Rate limiting, контекст диалога, retry с backoff, база знаний, разбиение длинных ответов.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from typing import Any, Dict, List

import structlog

from config import settings

log = structlog.get_logger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 15]


class RateLimiter:
    """Скользящее окно для rate limiting."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] > self._window:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max:
            return False
        self._timestamps.append(now)
        return True


class AIEngine:
    """Универсальная обёртка: Groq (Llama) или Gemini."""

    def __init__(self) -> None:
        self._provider = settings.ai_provider  # "groq" или "gemini"
        self._client: Any = None

        if self._provider == "groq":
            self._init_groq()
        else:
            self._init_gemini()

        self._system_prompt = self._load_system_prompt()
        self._knowledge_base = self._load_knowledge_base()
        self._global_limiter = RateLimiter(settings.global_rate_limit, 60)
        self._user_limiters: Dict[int, RateLimiter] = defaultdict(
            lambda: RateLimiter(settings.user_rate_limit, 60)
        )
        self._contexts: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=settings.ai_context_messages * 2)
        )
        log.info(
            "ai engine initialized", provider=self._provider, model=settings.ai_model
        )

    def _init_groq(self) -> None:
        from groq import Groq

        self._client = Groq(api_key=settings.groq_key.get_secret_value())

    def _init_gemini(self) -> None:
        from google import genai

        self._client = genai.Client(api_key=settings.gemini_key.get_secret_value())

    @staticmethod
    def _load_file(filename: str, fallback: str = "") -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", filename
        )
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            log.warning("file not found", path=path)
            return fallback

    def _load_system_prompt(self) -> str:
        return self._load_file(
            "system_prompt.txt",
            "Ты — Sonnet, AI-ассистент студенческой группы. Отвечай по существу.",
        )

    def _load_knowledge_base(self) -> str:
        return self._load_file("knowledge_base.txt")

    # ═══════════════════════════════════════════════════════
    # GROQ (Llama)
    # ═══════════════════════════════════════════════════════

    async def _call_groq(self, messages: list, system: str) -> str:
        """Вызов Groq API с retry."""
        full_messages = [{"role": "system", "content": system}] + messages

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=settings.ai_model,
                    messages=full_messages,
                    max_tokens=settings.ai_max_tokens,
                    temperature=settings.ai_temperature,
                )
                if response and response.choices and response.choices[0].message:
                    return (
                        response.choices[0].message.content
                        or "Не удалось сгенерировать ответ."
                    ).strip()
                return "Не удалось получить ответ от Groq."
            except Exception as e:
                last_error = e
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                    log.warning(
                        "groq retry",
                        attempt=attempt + 1,
                        delay=delay,
                        error=error_str[:100],
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise last_error  # type: ignore[misc]

    async def transcribe_audio(self, file_path: str) -> str:
        """Транскрибация аудио через Groq Whisper."""
        if self._provider != "groq" or not self._client:
            log.warning("transcribe_audio called but provider is not Groq")
            return "Транскрибация недоступна (требуется Groq)."

        try:
            log.info("starting transcription", file_path=file_path)

            # Whisper API runs extremely fast on Groq. We'll wrap the sync call in to_thread.
            def _do_transcribe():
                with open(file_path, "rb") as file:
                    transcription = self._client.audio.transcriptions.create(
                        file=(os.path.basename(file_path), file.read()),
                        model="whisper-large-v3",
                        response_format="text",
                        language="ru",  # Hinting that it might be Russian/Slovak mixed
                    )
                    return transcription

            result = await asyncio.to_thread(_do_transcribe)
            log.info("transcription successful", length=len(result))
            return result
        except Exception as e:
            log.error("failed to transcribe audio", error=str(e))
            return f"Ошибка при распознавании аудио: {e}"

    # ═══════════════════════════════════════════════════════
    # GEMINI (fallback)
    # ═══════════════════════════════════════════════════════

    async def _call_gemini(self, contents: list, system: str) -> str:
        """Вызов Gemini API с retry."""
        from google.genai import types

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=settings.ai_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=settings.ai_max_tokens,
                        temperature=settings.ai_temperature,
                    ),
                )
                if response:
                    return (response.text or "Не удалось сгенерировать ответ.").strip()
                return "Не удалось получить ответ от Gemini."
            except Exception as e:
                last_error = e
                error_str = str(e)
                if (
                    "429" in error_str
                    or "503" in error_str
                    or "RESOURCE_EXHAUSTED" in error_str
                ):
                    delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                    log.warning(
                        "gemini retry",
                        attempt=attempt + 1,
                        delay=delay,
                        error=error_str[:100],
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise last_error  # type: ignore[misc]

    # ═══════════════════════════════════════════════════════
    # ОСНОВНОЙ МЕТОД
    # ═══════════════════════════════════════════════════════

    async def generate_response(
        self,
        user_id: int,
        message: str,
        db_context: str = "",
        sender_name: str = "",
        chat_history: str = "",
    ) -> str:
        """Генерация ответа через выбранный провайдер."""

        if not self._user_limiters[user_id].allow():
            return "⏳ Слишком много запросов. Подожди минуту."
        if not self._global_limiter.allow():
            return "⏳ AI-модуль перегружен. Попробуй через минуту."

        context = self._contexts[user_id]
        context.append({"role": "user", "text": message})

        # Собираем системный промпт
        system_parts = [self._system_prompt]

        if self._knowledge_base:
            system_parts.append(f"\n\n═══ БАЗА ЗНАНИЙ ═══\n{self._knowledge_base}")

        if db_context:
            system_parts.append(f"\n\nДАННЫЕ ИЗ БАЗЫ ДАННЫХ:\n{db_context}")

        if chat_history:
            system_parts.append(
                f"\n\nПАМЯТЬ ЧАТА (все сообщения группы):\n{chat_history}"
            )

        if sender_name:
            system_parts.append(f"\nИмя собеседника: {sender_name}")

        full_system = "\n".join(system_parts)

        answer = ""
        elapsed_ms = 0

        try:
            start = time.monotonic()

            if self._provider == "groq":
                # Groq: OpenAI-совместимый формат
                messages = []
                for entry in context:
                    role = "user" if entry["role"] == "user" else "assistant"
                    messages.append({"role": role, "content": entry["text"]})
                answer = await self._call_groq(messages, full_system)
            else:
                # Gemini: собственный формат
                from google.genai import types

                contents = []
                for entry in context:
                    role = "user" if entry["role"] == "user" else "model"
                    contents.append(
                        types.Content(
                            role=role,
                            parts=[types.Part.from_text(text=entry["text"])],
                        )
                    )
                answer = await self._call_gemini(contents, full_system)

            elapsed_ms = int((time.monotonic() - start) * 1000)

            if (
                answer
                and not answer.startswith("⏳")
                and not answer.startswith("⚠️")
                and not answer.startswith("❌")
            ):
                context.append({"role": "model", "text": answer})

            log.info(
                "ai response",
                provider=self._provider,
                user_id=user_id,
                elapsed_ms=elapsed_ms,
                answer_len=len(answer) if answer else 0,
            )
            return answer or "Не удалось сгенерировать ответ."

        except Exception as e:
            error_str = str(e)
            log.error(
                "ai api error",
                provider=self._provider,
                error=error_str,
                user_id=user_id,
            )

            if (
                "429" in error_str
                or "RESOURCE_EXHAUSTED" in error_str
                or "rate" in error_str.lower()
            ):
                return "⚠️ AI временно недоступен из-за лимитов API. Попробуй через пару минут."
            elif "403" in error_str or "PERMISSION" in error_str:
                return "❌ Ошибка авторизации API. Обратись к администратору."
            else:
                return "⚠️ AI-модуль временно недоступен. Попробуй позже."

    def clear_context(self, user_id: int) -> None:
        if user_id in self._contexts:
            self._contexts[user_id].clear()


# Бэкворд-совместимость: GeminiEngine = AIEngine
GeminiEngine = AIEngine


def split_long_message(text: str, max_length: int = 4096) -> List[str]:
    """Разбить длинное сообщение на части по абзацам."""
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
