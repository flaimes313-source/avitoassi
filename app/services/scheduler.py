"""
Планировщик напоминаний на APScheduler.

Задачи:
- Планировать напоминания через 1/3/7 дней после создания/завершения задачи
- Отправлять напоминания в указанное время
- Сохранять задачи в PostgreSQL (переживают перезапуск BotHost)
- После напоминания предлагать внести статистику

Использование:
    from app.services.scheduler import scheduler_service
    await scheduler_service.start()           # при старте приложения
    await scheduler_service.stop()            # при остановке
    scheduler_service.schedule_reminder(...)  # при создании задачи
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from app.config import settings


class SchedulerService:
    """Обёртка над APScheduler."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        """Запускает планировщик с PostgreSQL job store."""
        if self._scheduler is not None:
            logger.warning("Scheduler уже запущен")
            return

        # Конвертируем asyncpg URL для SQLAlchemy
        # (psycopg2-совместимый URL)
        db_url = settings.database_url
        # SQLAlchemy ожидает postgresql:// (без +asyncpg)
        if db_url.startswith("postgresql://"):
            sqlalchemy_url = db_url
        else:
            sqlalchemy_url = db_url.replace("postgres://", "postgresql://")

        jobstores = {
            "default": SQLAlchemyJobStore(url=sqlalchemy_url)
        }

        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone="UTC",
        )
        self._scheduler.start()
        logger.info("Scheduler запущен (job store: PostgreSQL)")

    async def stop(self) -> None:
        """Останавливает планировщик."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Scheduler остановлен")

    # --------------------------------------------------------
    # ПЛАНИРОВАНИЕ НАПОМИНАНИЯ
    # --------------------------------------------------------
    def schedule_reminder(
        self,
        reminder_id: int,
        user_telegram_id: int,
        user_timezone: str,
        item_id: int | None = None,
        interval_days: int = 3,
        custom_text: str | None = None,
    ) -> bool:
        """
        Планирует напоминание через N дней.

        Возвращает True, если удалось запланировать.
        """
        if self._scheduler is None:
            logger.warning("Scheduler не запущен, напоминание не запланировано")
            return False

        # Время срабатывания — через N дней, в 12:00 по часовому поясу пользователя
        try:
            tz = ZoneInfo(user_timezone)
        except Exception:
            tz = ZoneInfo("Europe/Moscow")
            logger.warning(f"Невалидная timezone {user_timezone}, использую Europe/Moscow")

        now_local = datetime.now(tz)
        target_local = (now_local + timedelta(days=interval_days)).replace(
            hour=12, minute=0, second=0, microsecond=0,
        )
        target_utc = target_local.astimezone(timezone.utc)

        # Если уже прошло — сдвигаем на завтра
        if target_utc <= datetime.now(timezone.utc):
            target_utc = datetime.now(timezone.utc) + timedelta(minutes=5)

        job_id = f"reminder:{reminder_id}"

        try:
            self._scheduler.add_job(
                _send_reminder_job,
                trigger=DateTrigger(run_date=target_utc),
                id=job_id,
                name=f"Reminder {reminder_id}",
                replace_existing=True,
                kwargs={
                    "reminder_id": reminder_id,
                    "user_telegram_id": user_telegram_id,
                    "item_id": item_id,
                    "custom_text": custom_text,
                },
            )
            logger.info(
                f"Напоминание запланировано: id={reminder_id}, "
                f"tg={user_telegram_id}, на {target_utc.isoformat()}"
            )
            return True

        except Exception as e:
            logger.exception(f"Не удалось запланировать напоминание: {e}")
            return False

    def cancel_reminder(self, reminder_id: int) -> bool:
        """Отменяет запланированное напоминание."""
        if self._scheduler is None:
            return False
        job_id = f"reminder:{reminder_id}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info(f"Напоминание отменено: id={reminder_id}")
            return True
        except Exception as e:
            logger.debug(f"Не удалось отменить напоминание: {e}")
            return False


# ============================================================
# JOB: ОТПРАВКА НАПОМИНАНИЯ
# ============================================================
async def _send_reminder_job(
    reminder_id: int,
    user_telegram_id: int,
    item_id: int | None,
    custom_text: str | None,
) -> None:
    """
    Отправляет напоминание пользователю.
    Вызывается APScheduler'ом.
    """
    from app.main import bot
    from app.database import db
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    logger.info(f"Отправка напоминания id={reminder_id} → {user_telegram_id}")

    # Получаем данные напоминания
    try:
        reminder = await db.fetch_one(
            "SELECT * FROM reminders WHERE id = %s",
            (reminder_id,),
        )
        if not reminder:
            logger.warning(f"Напоминание {reminder_id} не найдено в БД")
            return

        # Проверяем, включено ли ещё
        if not reminder.get("enabled", True):
            logger.info(f"Напоминание {reminder_id} отключено пользователем")
            return

        # Формируем текст
        if custom_text:
            text = custom_text
        elif item_id:
            item = await db.fetch_one(
                "SELECT name FROM items WHERE id = %s",
                (item_id,),
            )
            item_name = item["name"] if item else "товар"
            text = (
                f"⏰ <b>Напоминание</b>\n\n"
                f"Как дела с продажей «{item_name}»?\n\n"
                f"Внеси статистику, чтобы я мог дать рекомендации:"
            )
        else:
            text = (
                "⏰ <b>Напоминание</b>\n\n"
                "Проверь, как идут дела с твоим объявлением."
            )

        # Клавиатура
        builder = InlineKeyboardBuilder()
        if item_id:
            builder.row(InlineKeyboardButton(
                text="📊 Внести статистику",
                callback_data=f"item:stats:{item_id}",
            ))
            builder.row(InlineKeyboardButton(
                text="📦 Открыть карточку",
                callback_data=f"item:view:{item_id}",
            ))
        builder.row(InlineKeyboardButton(
            text="⏰ Отключить напоминания",
            callback_data="settings:reminders",
        ))
        builder.row(InlineKeyboardButton(
            text="🏠 В главное меню",
            callback_data="menu:main",
        ))

        # Отправляем
        await bot.send_message(
            chat_id=user_telegram_id,
            text=text,
            reply_markup=builder.as_markup(),
        )

        # Помечаем как отправленное
        await db.execute(
            "UPDATE reminders SET sent_at = NOW() WHERE id = %s",
            (reminder_id,),
        )

        logger.info(f"Напоминание {reminder_id} отправлено")

    except Exception as e:
        logger.exception(f"Ошибка отправки напоминания {reminder_id}: {e}")


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
scheduler_service = SchedulerService()