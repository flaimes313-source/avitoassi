"""
Конфигурация приложения.

Читает переменные окружения из .env, валидирует их и предоставляет
типобезопасный доступ через объект `settings`.

Использование:
    from app.config import settings
    print(settings.telegram_bot_token)

При старте приложения Pydantic проверит все обязательные поля.
Если чего-то не хватает — приложение упадёт сразу, а не в момент
первого обращения к внешнему API.
"""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Все настройки проекта.

    Значения читаются из:
    1. Переменных окружения (приоритет на BotHost)
    2. Файла .env (для локальной разработки)
    3. Значений по умолчанию (если указаны)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,      # TELEGRAM_BOT_TOKEN == telegram_bot_token
        extra="ignore",            # лишние переменные в .env не ломают запуск
    )

    # ========================================================
    # TELEGRAM
    # ========================================================
    telegram_bot_token: str = Field(
        ...,
        description="Токен бота от @BotFather",
    )
    admin_telegram_id: int = Field(
        ...,
        description="Telegram ID главного администратора",
    )

    # ========================================================
    # WEBHOOK / BOTHOST
    # ========================================================
    webhook_base_url: str = Field(
        default="",
        description="Публичный URL приложения (выдаёт BotHost)",
    )
    webhook_path: str = Field(
        default="/webhook",
        description="Путь для приёма обновлений от Telegram",
    )
    webhook_secret: str = Field(
        default="change-me",
        description="Секрет для проверки, что запрос пришёл от Telegram",
    )
    bot_mode: Literal["polling", "webhook"] = Field(
        default="polling",
        description="Режим работы: polling (локально) или webhook (BotHost)",
    )

    # ========================================================
    # DATABASE
    # ========================================================
    database_url: str = Field(
        ...,
        description="Строка подключения к PostgreSQL",
    )
    db_pool_min_size: int = Field(default=1, description="Минимум соединений в пуле")
    db_pool_max_size: int = Field(default=10, description="Максимум соединений в пуле")

    # ========================================================
    # YANDEX CLOUD
    # ========================================================
    yandex_api_key: str = Field(..., description="API-ключ сервисного аккаунта")
    yandex_folder_id: str = Field(..., description="ID каталога Yandex Cloud")
    yandex_gpt_model: str = Field(
        default="yandexgpt",
        description="Модель: yandexgpt-lite / yandexgpt / yandexgpt-pro",
    )
    yandex_gpt_temperature: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Температура генерации (0.0–1.0)",
    )
    yandex_gpt_max_tokens: int = Field(
        default=2000,
        gt=0,
        description="Максимум токенов в ответе",
    )
    image_analysis_enabled: bool = Field(
        default=True,
        description="Включён ли анализ изображений (Vision)",
    )

    # ========================================================
    # YOOKASSA
    # ========================================================
    yookassa_shop_id: str = Field(..., description="Shop ID в ЮKassa")
    yookassa_secret_key: str = Field(..., description="Secret key в ЮKassa")
    yookassa_return_url: str = Field(
        default="https://t.me",
        description="URL возврата после оплаты",
    )

    # ========================================================
    # ТАРИФЫ И ЛИМИТЫ (блок 11 ТЗ)
    # ========================================================
    free_monthly_tasks: int = Field(
        default=3,
        ge=0,
        description="Задач в месяц на тарифе FREE",
    )
    pro_daily_tasks: int = Field(
        default=5,
        ge=0,
        description="Задач в день на тарифе PRO",
    )
    pro_price_rub: int = Field(
        default=490,
        gt=0,
        description="Цена PRO в рублях",
    )
    pro_duration_days: int = Field(
        default=30,
        gt=0,
        description="Срок подписки PRO в днях",
    )

    # ========================================================
    # ПРИВАТНОСТЬ И ФАЙЛЫ (блок 13 ТЗ)
    # ========================================================
    photo_retention_hours: int = Field(
        default=24,
        ge=1,
        description="Сколько часов хранить оригиналы фото",
    )
    max_photo_size_mb: int = Field(
        default=10,
        gt=0,
        description="Максимальный размер фото в МБ",
    )

    # ========================================================
    # ОБЩИЕ
    # ========================================================
    default_timezone: str = Field(
        default="Europe/Moscow",
        description="Часовой пояс по умолчанию",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Уровень логирования",
    )
    environment: Literal["dev", "prod"] = Field(
        default="dev",
        description="Окружение: dev или prod",
    )

    # ========================================================
    # ВАЛИДАТОРЫ
    # ========================================================
    @field_validator("webhook_path")
    @classmethod
    def _ensure_webhook_path_starts_with_slash(cls, v: str) -> str:
        """Гарантирует, что путь начинается со слеша."""
        if not v.startswith("/"):
            return "/" + v
        return v

    @field_validator("database_url")
    @classmethod
    def _ensure_postgres_scheme(cls, v: str) -> str:
        """Проверяет, что строка подключения — PostgreSQL."""
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                "DATABASE_URL должен начинаться с postgresql:// или postgres://"
            )
        return v

    @field_validator("webhook_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        """Убирает слеш в конце URL, чтобы не было двойных //."""
        return v.rstrip("/")

    # ========================================================
    # ВЫЧИСЛЯЕМЫЕ СВОЙСТВА
    # ========================================================
    @property
    def webhook_url(self) -> str:
        """Полный URL webhook для регистрации в Telegram."""
        return f"{self.webhook_base_url}{self.webhook_path}"

    @property
    def is_production(self) -> bool:
        """True, если окружение — prod."""
        return self.environment == "prod"

    @property
    def is_dev(self) -> bool:
        """True, если окружение — dev."""
        return self.environment == "dev"


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
# Создаётся один раз при импорте модуля.
# Если обязательная переменная отсутствует — упадёт с понятной ошибкой.
settings = Settings()