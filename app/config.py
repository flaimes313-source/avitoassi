"""
Конфигурация приложения.
"""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки проекта."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ========================================================
    # TELEGRAM
    # ========================================================
    telegram_bot_token: str = Field(..., description="Токен бота от @BotFather")
    admin_telegram_id: int = Field(..., description="Telegram ID администратора")

    # ========================================================
    # WEBHOOK / BOTHOST
    # ========================================================
    webhook_base_url: str = Field(default="", description="Публичный URL приложения")
    webhook_path: str = Field(default="/webhook", description="Путь для webhook")
    webhook_secret: str = Field(default="change-me", description="Секрет webhook")
    bot_mode: Literal["polling", "webhook"] = Field(default="polling")

    # ========================================================
    # DATABASE
    # ========================================================
    database_url: str = Field(..., description="Строка подключения к PostgreSQL")
    db_pool_min_size: int = Field(default=1)
    db_pool_max_size: int = Field(default=10)

    # ========================================================
    # GIGACHAT (основная нейросеть)
    # ========================================================
    gigachat_credentials: str = Field(
        ...,
        description="Ключ авторизации GigaChat (base64 client_id:client_secret)",
    )
    gigachat_scope: str = Field(
        default="GIGACHAT_API_PERS",
        description="Scope: GIGACHAT_API_PERS / GIGACHAT_API_B2B / GIGACHAT_API_CORP",
    )
    gigachat_model: str = Field(
        default="GigaChat-2-Pro",
        description="Модель: GigaChat-2, GigaChat-2-Pro, GigaChat-2-Max",
    )
    gigachat_temperature: float = Field(default=0.6, ge=0.0, le=1.0)
    gigachat_max_tokens: int = Field(default=2000, gt=0)
    gigachat_verify_ssl: bool = Field(
        default=False,
        description="Проверять SSL-сертификат (для dev лучше false)",
    )
    gigachat_ca_bundle_file: str = Field(
        default="",
        description="Путь к файлу CA-сертификата Минцифры",
    )

    # ========================================================
    # YANDEX CLOUD (fallback)
    # ========================================================
    yandex_api_key: str = Field(default="", description="API-ключ Yandex Cloud")
    yandex_folder_id: str = Field(default="", description="ID каталога Yandex")
    yandex_gpt_model: str = Field(default="yandexgpt")
    yandex_gpt_temperature: float = Field(default=0.6, ge=0.0, le=1.0)
    yandex_gpt_max_tokens: int = Field(default=2000, gt=0)
    image_analysis_enabled: bool = Field(default=True)

    # ========================================================
    # YOOKASSA
    # ========================================================
    yookassa_shop_id: str = Field(..., description="Shop ID в ЮKassa")
    yookassa_secret_key: str = Field(..., description="Secret key в ЮKassa")
    yookassa_return_url: str = Field(default="https://t.me")

    # ========================================================
    # ТАРИФЫ И ЛИМИТЫ
    # ========================================================
    free_monthly_tasks: int = Field(default=3, ge=0)
    pro_daily_tasks: int = Field(default=5, ge=0)
    pro_price_rub: int = Field(default=490, gt=0)
    pro_duration_days: int = Field(default=30, gt=0)

    # ========================================================
    # ПРИВАТНОСТЬ И ФАЙЛЫ
    # ========================================================
    photo_retention_hours: int = Field(default=24, ge=1)
    max_photo_size_mb: int = Field(default=10, gt=0)

    # ========================================================
    # ОБЩИЕ
    # ========================================================
    default_timezone: str = Field(default="Europe/Moscow")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    environment: Literal["dev", "prod"] = Field(default="dev")

    # ========================================================
    # НАПОМИНАНИЯ
    # =======================================================
    default_reminder_days: int = Field(
        default=3,
        description="Интервал напоминаний по умолчанию (дни)",
    )

    # ========================================================
    # ВАЛИДАТОРЫ
    # ========================================================
    @field_validator("webhook_path")
    @classmethod
    def _ensure_webhook_path_starts_with_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            return "/" + v
        return v

    @field_validator("database_url")
    @classmethod
    def _ensure_postgres_scheme(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL должен начинаться с postgresql:// или postgres://")
        return v

    @field_validator("webhook_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    # ========================================================
    # ВЫЧИСЛЯЕМЫЕ СВОЙСТВА
    # ========================================================
    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url}{self.webhook_path}"

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def is_dev(self) -> bool:
        return self.environment == "dev"

    @property
    def has_yandex_fallback(self) -> bool:
        """Есть ли настроенный YandexGPT для fallback."""
        return bool(self.yandex_api_key and self.yandex_folder_id)


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
settings = Settings()