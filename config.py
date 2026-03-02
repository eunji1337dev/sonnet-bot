"""
Конфигурация бота Sonnet.
Типизированные настройки через pydantic-settings v2.
Все секреты загружаются из .env.
"""

from __future__ import annotations

from typing import List

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки бота Sonnet."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ── Токены ──────────────────────────────────────────
    bot_token: SecretStr
    gemini_key: SecretStr = SecretStr("")
    groq_key: SecretStr = SecretStr("")

    # ── Группа ──────────────────────────────────────────
    group_chat_id: int = 0
    timezone: str = "Europe/Bratislava"
    language: str = "ru"

    # ── Администраторы (Telegram user IDs) ──────────────
    admin_ids: str = ""

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: str) -> str:
        return v

    @property
    def admin_id_list(self) -> List[int]:
        if not self.admin_ids:
            return []
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip()]

    # ── AI ──────────────────────────────────────────────
    ai_provider: str = "groq"  # "groq" или "gemini"
    ai_model: str = "llama-3.1-8b-instant"
    ai_max_tokens: int = 2048
    ai_temperature: float = 0.7
    ai_context_messages: int = 5

    # ── Rate limits ─────────────────────────────────────
    user_rate_limit: int = 20  # запросов/мин от одного пользователя
    global_rate_limit: int = 28  # запросов/мин глобально
    spam_msg_count: int = 5  # сообщений за spam_window_sec = антиспам
    spam_window_sec: int = 10

    # ── Сообщения ───────────────────────────────────────
    max_message_length: int = 4096

    # ── Расписание автоматических сообщений ──────────────
    morning_schedule_time: str = "07:30"
    weekly_summary_time: str = "20:00"
    weekly_summary_day: int = 6  # 0=Mon ... 6=Sun

    # ── База данных ─────────────────────────────────────
    database_path: str = "data/sonnet.db"

    # ── Учебный год ─────────────────────────────────────
    current_semester: str = "winter_2025"


settings = Settings()  # type: ignore[call-arg]
