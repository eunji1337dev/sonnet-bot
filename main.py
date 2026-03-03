"""
Sonnet — AI-ассистент группы Europske studia.
Точка входа: инициализация бота, подключение роутеров, lifecycle.
"""

from __future__ import annotations

import os
import os
import asyncio
import logging
import sys

from aiohttp import web
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


async def async_main() -> None:
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

    # 1. Запускаем минимальный HTTP-сервер для healthcheck (Render Web Service)
    app = web.Application()
    
    async def health_handler(request: web.Request) -> web.Response:
        return web.Response(text="OK", status=200)
    
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    
    # site.start() запускает фоновую задачу прослушивания порта,
    # что работает конкурентно с циклом поллинга aiogram.
    await site.start()
    structlog.get_logger(__name__).info(f"Health server listening on port {port}")

    # 2. Self-ping to keep Render Web Service awake
    url = os.environ.get("RENDER_EXTERNAL_URL")
    keep_alive_task = None
    if url:
        async def _keep_alive() -> None:
            import aiohttp
            ping_url = f"{url}/health" if not url.endswith("/health") else url
            while True:
                await asyncio.sleep(600)  # 10 минут
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(ping_url, timeout=10) as response:
                            structlog.get_logger(__name__).info("keep-alive ping", status=response.status)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    structlog.get_logger(__name__).error("keep-alive failed", error=str(e))
        
        keep_alive_task = asyncio.create_task(_keep_alive())

    # 3. Оборачиваем поллинг в задачу (Render-безопасно)
    polling_task = asyncio.create_task(
        dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "chat_member"],
        )
    )

    try:
        # aiogram сам перехватит сигналы остановки (SIGTERM/SIGINT) и корректно завершится
        await polling_task
    except asyncio.CancelledError:
        structlog.get_logger(__name__).info("Polling task was cancelled.")
    finally:
        if keep_alive_task:
            keep_alive_task.cancel()
        await runner.cleanup()


def main() -> None:
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
