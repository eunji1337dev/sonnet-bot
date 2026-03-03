"""
Main entry point (2026 Enterprise Edition).
Integrates: OpenTelemetry, FastAPI (Health/Webhooks), Aiogram Polling, APScheduler, and the AI Engine.
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import asynccontextmanager

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI
import uvicorn

# OpenTelemetry configuration
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from config import settings
from core import database as db
from core.ai_engine import AIEngine
from core.scheduler import EnterpriseScheduler
from handlers import commands, messages, callbacks
from middleware.auth import AuthMiddleware
from middleware.logging import LoggingMiddleware

# Initialize Tracer
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer_provider().get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(ConsoleSpanExporter())
)

log = structlog.get_logger(__name__)

bot = Bot(
    token=settings.bot_token.get_secret_value(),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
ai_engine = AIEngine()
scheduler = EnterpriseScheduler(bot)


def setup_handlers(dispatcher: Dispatcher, ai: AIEngine) -> None:
    dispatcher.include_router(commands.router)
    dispatcher.include_router(callbacks.router)
    # Inject engine dependencies explicitly to the message handlers
    messages.router.message.middleware(AuthMiddleware())
    dispatcher.include_router(messages.router)
    
    # Store engine globally in dispatcher for easy access in handlers if needed
    dispatcher["ai_engine"] = ai


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan events for startup/shutdown."""
    log.info("Starting Enterprise Sonnet Bot (FastAPI)")
    await db.init_db()

    setup_handlers(dp, ai_engine)
    dp.update.outer_middleware(LoggingMiddleware())

    # Start APScheduler
    scheduler.start()

    # Start background polling task
    log.info("Starting Telegram polling")
    polling_task = asyncio.create_task(dp.start_polling(bot))

    yield

    log.info("Shutting down... Stopping services")
    scheduler.shutdown()
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass
    finally:
        await bot.session.close()
        await db.close_db()
        log.info("Shutdown complete.")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check():
    """Endpoint for UptimeRobot to ping to prevent Render free-tier sleep."""
    with tracer.start_as_current_span("health_check"):
        return {"status": "healthy"}


def main() -> None:
    # Build a stable Server config explicitly
    port = int(os.getenv("PORT", 8000))
    host = "0.0.0.0"
    
    log.info("Starting Uvicorn server", host=host, port=port)
    
    # Passing the app instance directly prevents double-import race conditions
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        loop="uvloop",
        log_level="info",
        # Ensures Uvicorn propagates OS signals correctly to trigger lifespan teardown
        timeout_graceful_shutdown=15 
    )
    server = uvicorn.Server(config)
    
    # Run the server synchronously
    server.run()


if __name__ == "__main__":
    import uvloop
    uvloop.install()
    try:
        main()
    except KeyboardInterrupt:
        log.info("Application interrupted by user.")
    except Exception as e:
        log.error("Fatal Application Error", error=str(e))
