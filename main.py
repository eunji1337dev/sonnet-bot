"""
Sonnet — AI-ассистент группы Europske studia.
Точка входа: инициализация бота, подключение роутеров, lifecycle.
"""

from __future__ import annotations

import os
import asyncio
import logging
import sys
from typing import Any

from aiohttp import web

import signal
import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor

from config import settings
from core.ai_engine import GeminiEngine
from core import database as db
from core.scheduler import scheduler_loop
from handlers import commands as cmd_handlers
from handlers import messages as msg_handlers
from handlers import callbacks as cb_handlers
from handlers import admin as admin_handlers
from handlers import media as media_handlers
from modules.moderation import router as moderation_router
from handlers.middleware import (
    LoggingMiddleware,
    PrivateMessageFilterMiddleware,
    UserTrackingMiddleware,
    AntiSpamMiddleware,
)


# ═══════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════


def _setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


# ═══════════════════════════════════════════════════════
# LIFECYCLE
# ═══════════════════════════════════════════════════════

_scheduler_task = None
_engine: GeminiEngine | None = None


async def start_dummy_server() -> None:
    """Заглушка для Render.com (Web Service), чтобы порт прослушивался."""
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Sonnet Bot is alive!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    structlog.get_logger(__name__).info(f"Dummy HTTP server started on port {port}")


async def on_startup(bot: Bot) -> None:
    log = structlog.get_logger(__name__)

    # Инициализация БД
    await db.init_db()

    # Инициализация AI-движка
    global _engine
    _engine = GeminiEngine()

    # Передать engine в обработчики
    cmd_handlers.set_engine(_engine)
    msg_handlers.set_engine(_engine)
    media_handlers.set_engine(_engine)

    # Сохранить info бота для фильтра сообщений
    me = await bot.me()
    msg_handlers.set_bot_info(me)

    log.info("Sonnet запущен", bot=me.username, id=me.id)

    # Зарегистрировать команды в Telegram
    commands = [
        BotCommand(command="start", description="Начало работы"),
        BotCommand(command="help", description="Справка по командам"),
        BotCommand(command="schedule", description="Расписание на сегодня"),
        BotCommand(command="schedule_week", description="Расписание на неделю"),
        BotCommand(command="next", description="Ближайшая пара"),
        BotCommand(command="exams", description="Экзамены"),
        BotCommand(command="deadlines", description="Дедлайны"),
        BotCommand(command="subjects", description="Список предметов"),
        BotCommand(command="links", description="Полезные ссылки"),
        BotCommand(command="faq", description="Частые вопросы"),
        BotCommand(command="ask", description="Задать вопрос AI"),
        BotCommand(command="translate", description="Перевод RU/UA/SK"),
        BotCommand(command="letter", description="Письмо преподавателю"),
        BotCommand(command="remind", description="Напоминание"),
        BotCommand(command="weather", description="Погода в Прешове"),
        BotCommand(command="id", description="Твой Telegram ID"),
    ]
    await bot.set_my_commands(commands)

    # Запуск планировщика
    global _scheduler_task
    _scheduler_task = asyncio.create_task(scheduler_loop(bot))


def _setup_otel() -> None:
    """Настройка OpenTelemetry."""
    provider = TracerProvider()
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    AsyncioInstrumentor().instrument()


async def shutdown(
    loop: asyncio.AbstractEventLoop, sig: signal.Signals | None = None
) -> None:
    """Graceful shutdown: отмена задач и выход."""
    if sig:
        structlog.get_logger(__name__).info(f"Получен сигнал: {sig.name}")

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]

    structlog.get_logger(__name__).info(f"Отмена {len(tasks)} задач...")
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


async def on_shutdown(bot: Bot) -> None:
    log = structlog.get_logger(__name__)

    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()

    await db.close_db()
    log.info("Sonnet остановлен")
    await bot.session.close()


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════


def main() -> None:
    _setup_logging()

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode="HTML"),
    )

    dp = Dispatcher()

    # Middleware
    dp.message.middleware(PrivateMessageFilterMiddleware())
    dp.message.middleware(AntiSpamMiddleware())
    dp.message.middleware(LoggingMiddleware())
    dp.message.middleware(UserTrackingMiddleware())

    dp.callback_query.middleware(PrivateMessageFilterMiddleware())
    dp.callback_query.middleware(AntiSpamMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())

    # Порядок важен: команды -> админ -> callbacks -> модерация -> медиа -> сообщения (catch-all)
    dp.include_router(cmd_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(cb_handlers.router)
    dp.include_router(moderation_router)
    dp.include_router(media_handlers.router)
    dp.include_router(msg_handlers.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    _setup_otel()

    loop = asyncio.get_event_loop()

    # Регистрация сигналов
    def signal_handler(sig_received: Any) -> None:
        asyncio.create_task(shutdown(loop, sig_received))

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, signal_handler, sig)

    try:
        loop.create_task(
            dp.start_polling(
                bot,
                allowed_updates=["message", "callback_query", "chat_member"],
            )
        )
        loop.create_task(start_dummy_server())
        loop.run_forever()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
