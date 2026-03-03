"""
Обработка текстовых сообщений.
Логика:
- ЛС → всегда AI
- Группа → сохраняет ВСЕ сообщения в БД
- Группа → отвечает ТОЛЬКО на вопросы (реплаем)
- Группа → отвечает на прямые обращения ("Sonnet,") и @mention
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from modules.moderation import check_spam

import structlog
from aiogram import Router, types
from aiogram.filters import Filter

from core import database as db
from core.ai_engine import GeminiEngine, split_long_message
from aiogram.dispatcher.event.bases import SkipHandler

log = structlog.get_logger(__name__)

router = Router(name="messages")

_engine: Optional[GeminiEngine] = None
_bot_info: Optional[types.User] = None


def set_engine(engine: GeminiEngine) -> None:
    global _engine
    _engine = engine


def set_bot_info(info: types.User) -> None:
    global _bot_info
    _bot_info = info


# ═══════════════════════════════════════════════════════
# QUESTION DETECTION
# ═══════════════════════════════════════════════════════

_QUESTION_PATTERNS = [
    # Знаки вопроса
    r"\?",
    # Русские/украинские вопросительные слова
    r"(?i)^(кто|что|где|когда|как|зачем|почему|какой|какая|какие|какое|сколько|куда|откуда|чей|кому|чем|ли)\b",
    # Словацкие вопросительные слова
    r"(?i)^(kto|čo|kde|kedy|ako|prečo|aký|aká|aké|koľko|kam|odkiaľ)\b",
    # Английские вопросительные слова
    r"(?i)^(who|what|where|when|how|why|which|whose|is|are|do|does|can|will|should)\b",
    # Фразы-запросы
    r"(?i)(подскажите|скажите|расскажи|объясни|помоги|напомни|кто.?нибудь знает|а можно|есть ли)",
    r"(?i)(не знаете|не подскажете|кто знает|кто в курсе|что насчет|что по)",
]

_QUESTION_RE = [re.compile(p) for p in _QUESTION_PATTERNS]


def _is_question(text: str) -> bool:
    """Определить, является ли текст вопросом."""
    text = text.strip()
    for pattern in _QUESTION_RE:
        if pattern.search(text):
            return True
    return False


# ═══════════════════════════════════════════════════════
# FILTERS
# ═══════════════════════════════════════════════════════


class ShouldRespondFilter(Filter):
    """Фильтр: бот должен ответить на это сообщение?"""

    async def __call__(self, message: types.Message) -> bool:
        if not message.text:
            return False

        # ЛС — разрешаем, так как middleware уже заблокировал посторонних
        if message.chat.type == "private":
            return True

        text = message.text.lower().strip()

        # Прямое обращение: "Sonnet, ..."
        if text.startswith("sonnet,") or text.startswith("sonnet "):
            log.info("ShouldRespondFilter: direct text mention", text=text)
            return True

        # @упоминание
        if _bot_info and _bot_info.username:
            if f"@{_bot_info.username.lower()}" in text:
                log.info(
                    "ShouldRespondFilter: username mention",
                    text=text,
                    username=_bot_info.username,
                )
                return True
        else:
            log.warning("ShouldRespondFilter: _bot_info is None")

        # Ответ на сообщение бота
        if message.reply_to_message and message.reply_to_message.from_user:
            if _bot_info and message.reply_to_message.from_user.id == _bot_info.id:
                log.info("ShouldRespondFilter: reply to bot")
                return True

        # Вопрос в группе — автоответ
        if _is_question(message.text):
            log.info("ShouldRespondFilter: question detected")
            return True

        log.info("ShouldRespondFilter: ignored", text=text)
        return False


class SaveMessageFilter(Filter):
    """Фильтр: сохранять все текстовые сообщения в группе."""

    async def __call__(self, message: types.Message) -> bool:
        if not message.text:
            return False
        # Сохраняем только групповые сообщения
        return message.chat.type in ("group", "supergroup")


def _extract_question(text: str) -> str:
    """Извлечь вопрос из обращения."""
    cleaned = re.sub(r"^sonnet[,\s]+", "", text, flags=re.IGNORECASE).strip()
    if _bot_info and _bot_info.username:
        cleaned = re.sub(
            rf"@{re.escape(_bot_info.username)}\s*", "", cleaned, flags=re.IGNORECASE
        ).strip()
    return cleaned or text


# ═══════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════


@router.message(SaveMessageFilter())
async def save_group_message(message: types.Message) -> None:
    """Сохранить каждое групповое сообщение в БД (не блокирует дальнейшую обработку)."""
    user = message.from_user
    if not user:
        return
    try:
        reply_id = (
            message.reply_to_message.message_id if message.reply_to_message else None
        )
        await db.save_chat_message(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            chat_id=message.chat.id,
            text=message.text or "",
            reply_to_message_id=reply_id,
        )
    except Exception as e:
        structlog.get_logger(__name__).debug("Message logging failed", error=str(e))

    # ОЧЕНЬ ВАЖНО: пропускаем событие дальше, чтобы сработал handle_ai_message
    raise SkipHandler()


# ═══════════════════════════════════════════════════════
# ЗАПОМНИ (сохранение заметок из ЛС)
# ═══════════════════════════════════════════════════════

_REMEMBER_PATTERNS = re.compile(
    r"^(?:запомни|запомни:|запам['ʼ]ятай|remember|zapamataj)[:\s]+(.+)",
    flags=re.IGNORECASE | re.DOTALL,
)


@router.message(
    lambda m: m.chat.type == "private" and m.text and _REMEMBER_PATTERNS.match(m.text)
)
async def handle_remember(message: types.Message) -> None:
    """Сохранить заметку из ЛС по запросу 'запомни: ...'"""
    match = _REMEMBER_PATTERNS.match(message.text or "")
    if not match:
        return
    note_text = match.group(1).strip()
    if not note_text:
        await message.reply("Напиши что запомнить после 'запомни:'")
        return

    user = message.from_user
    sender = user.first_name if user else "Кто-то"

    await db.add_note(
        category="memory",
        title=f"Заметка от {sender}",
        content=note_text,
        created_by=str(user.id) if user else "",
    )
    await message.reply(f"✅ Запомнил: {note_text}")


@router.message(ShouldRespondFilter())
async def handle_ai_message(message: types.Message) -> None:
    """Обработать сообщение через AI."""
    if not _engine:
        log.warning("handle_ai_message: _engine is None")
        return

    user = message.from_user
    if not user:
        log.warning("handle_ai_message: user is None")
        return

    # Антиспам: блокируем спамеров до отправки в AI
    if check_spam(user.id):
        log.warning("handle_ai_message: check_spam returned True", user_id=user.id)
        return

    # Проверка "Тихого режима" в группах
    if message.chat.type in ("group", "supergroup"):
        is_quiet = await db.get_setting("is_quiet_mode", "off")
        if is_quiet == "on":
            log.info("handle_ai_message: quiet mode is ON, skipping response")
            return

    text = message.text or ""
    question = _extract_question(text)

    if not question.strip():
        log.warning("handle_ai_message: extracted question is empty", original=text)
        return

    log.info("handle_ai_message: processing question", question=question)

    # Typing indicator
    bot = message.bot
    if bot:
        try:
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        except Exception as e:
            structlog.get_logger(__name__).debug(
                "Chat action in AI message failed", error=str(e)
            )

    # Контекст из базы
    db_context = await _build_message_context(question)

    # Память: недавние сообщения + поиск по всей истории
    chat_history = ""
    if message.chat.type in ("group", "supergroup"):
        chat_history = await _build_chat_memory(message.chat.id, question)

    answer = await _engine.generate_response(
        user.id,
        question,
        db_context=db_context,
        sender_name=user.first_name or "",
        chat_history=chat_history,
    )

    if not answer or not answer.strip():
        return

    # Логируем
    await db.log_ai_request(user.id, question, answer)

    # Отправляем ответ (в группе — реплаем)
    for part in split_long_message(answer):
        try:
            await message.reply(part)
        except Exception as e:
            log.error("failed to send reply", error=str(e))
            break
        await asyncio.sleep(0.3)


async def _build_message_context(question: str) -> str:
    """Собрать контекст из базы данных."""
    from handlers.commands import _build_db_context

    return await _build_db_context(question)


# ═══════════════════════════════════════════════════════
# SMART MEMORY
# ═══════════════════════════════════════════════════════

_STOPWORDS = {
    "а",
    "в",
    "и",
    "к",
    "на",
    "не",
    "по",
    "с",
    "у",
    "я",
    "он",
    "она",
    "мы",
    "вы",
    "их",
    "его",
    "это",
    "что",
    "как",
    "ещё",
    "еще",
    "все",
    "уже",
    "ли",
    "то",
    "да",
    "нет",
    "бы",
    "же",
    "ну",
    "где",
    "кто",
    "чем",
    "для",
    "из",
    "до",
    "так",
    "или",
    "вот",
    "тут",
    "там",
    "но",
    "от",
    "the",
    "is",
    "are",
    "was",
    "do",
    "a",
    "an",
    "in",
    "on",
    "to",
    "of",
    "for",
    "and",
    "or",
    "je",
    "na",
    "to",
    "sa",
    "za",
    "od",
    "do",
    "ako",
    "ale",
    "že",
    "by",
}


def _extract_keywords(text: str) -> list:
    """Извлечь ключевые слова из вопроса (без стоп-слов, 3+ символа)."""
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁіІїЇєЄґҐčšžťďňĺŕäôúýáéíóöüĆŠŽ]+", text.lower())
    keywords = [w for w in words if len(w) >= 3 and w not in _STOPWORDS]
    return keywords[:8]  # Макс 8 ключевых слов


def _format_messages(messages: list) -> str:
    """Форматировать сообщения в строку для контекста."""
    lines = []
    for msg in messages:
        name = msg.get("first_name", "?")
        txt = msg.get("text", "")[:200]
        ts = msg.get("created_at", "")[:16] if msg.get("created_at") else ""
        lines.append(f"[{ts}] {name}: {txt}")
    return "\n".join(lines)


async def _build_chat_memory(chat_id: int, question: str) -> str:
    """Собрать полный контекст из памяти: недавние + релевантные из истории + заметки."""
    parts = []

    # 1. Последние 30 сообщений (недавний контекст)
    recent = await db.get_recent_messages(chat_id, limit=30)
    if recent:
        parts.append("=== ПОСЛЕДНИЕ СООБЩЕНИЯ ===")
        parts.append(_format_messages(recent))

    # 2. Поиск по всей истории по ключевым словам вопроса
    keywords = _extract_keywords(question)
    if keywords:
        found = await db.search_messages(chat_id, keywords, limit=20)
        # Убрать дубли с недавними
        recent_texts = {m.get("text", "") for m in recent} if recent else set()
        unique_found = [m for m in found if m.get("text", "") not in recent_texts]
        if unique_found:
            parts.append(f"\n=== ИЗ ИСТОРИИ (по: {', '.join(keywords)}) ===")
            parts.append(_format_messages(unique_found))

    return "\n".join(parts)
