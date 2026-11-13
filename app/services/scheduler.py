"""
Планировщик напоминаний на APScheduler.

Задачи:
- Планировать напоминания через 1/3/7 дней после завершения задачи
- Ежедневная проверка истекающих PRO (за 1 день)
- Отслеживание блокировки бота (bot_blocked)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from app.config import settings


def _build_sqlalchemy_url(db_url: str) -> str:
    """Преобразует psycopg3-URL в SQLAlchemy-совместимый (+psycopg)."""
    if db_url.startswith("postgresql+psycopg://"):
        return db_url
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if db_url.startswith("postgres://"):
        return db_url.replace("postgres://", "postgresql+psycopg://", 1)
    return db_url


class SchedulerService:
    """Обёртка над APScheduler."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        """Запускает планировщик с PostgreSQL job store."""
        if self._scheduler is not None:
            logger.warning("Scheduler уже запущен")
            return

        sqlalchemy_url = _build_sqlalchemy_url(settings.database_url)
        safe_url = sqlalchemy_url.split("@")[-1] if "@" in sqlalchemy_url else "?"
        logger.info(f"SQLAlchemy URL (без пароля): ***@{safe_url}")

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
    # НАПОМИНАНИЯ ПО ЗАДАЧАМ
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
        """Планирует напоминание через N дней."""
        if self._scheduler is None:
            logger.warning("Scheduler не запущен, напоминание не запланировано")
            return False

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

    # --------------------------------------------------------
    # ЕЖЕДНЕВНАЯ ПРОВЕРКА PRO
    # --------------------------------------------------------
    def schedule_daily_pro_check(self) -> None:
        """Планирует ежедневную проверку PRO (10:00 UTC)."""
        if self._scheduler is None:
            logger.warning("Scheduler не запущен, ежедневная проверка PRO не запланирована")
            return

        try:
            self._scheduler.add_job(
                _check_expiring_pro_job,
                trigger=CronTrigger(hour=10, minute=0),
                id="daily_pro_check",
                name="Daily PRO check",
                replace_existing=True,
            )
            logger.info("Ежедневная проверка PRO запланирована (10:00 UTC)")
        except Exception as e:
            logger.exception(f"Не удалось запланировать проверку PRO: {e}")


# ============================================================
# JOB: ОТПРАВКА НАПОМИНАНИЯ
# ============================================================
async def _send_reminder_job(
    reminder_id: int,
    user_telegram_id: int,
    item_id: int | None,
    custom_text: str | None,
) -> None:
    """Отправляет напоминание пользователю."""
    from app.main import bot
    from app.database import db
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    from aiogram.exceptions import TelegramForbiddenError

    logger.info(f"Отправка напоминания id={reminder_id} → {user_telegram_id}")

    try:
        reminder = await db.fetch_one(
            "SELECT * FROM reminders WHERE id = %s",
            (reminder_id,),
        )
        if not reminder:
            logger.warning(f"Напоминание {reminder_id} не найдено в БД")
            return

        if not reminder.get("enabled", True):
            logger.info(f"Напоминание {reminder_id} отключено пользователем")
            return

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

        try:
            await bot.send_message(
                chat_id=user_telegram_id,
                text=text,
                reply_markup=builder.as_markup(),
            )
        except TelegramForbiddenError:
            logger.info(f"Пользователь {user_telegram_id} заблокировал бота")
            await db.execute(
                "UPDATE users SET bot_blocked = TRUE WHERE telegram_id = %s",
                (user_telegram_id,),
            )
            await db.execute(
                "UPDATE reminders SET sent_at = NOW() WHERE id = %s",
                (reminder_id,),
            )
            return

        await db.execute(
            "UPDATE reminders SET sent_at = NOW() WHERE id = %s",
            (reminder_id,),
        )

        # Разблокировался — сбрасываем флаг, если был
        await db.execute(
            "UPDATE users SET bot_blocked = FALSE WHERE telegram_id = %s AND bot_blocked = TRUE",
            (user_telegram_id,),
        )

        logger.info(f"Напоминание {reminder_id} отправлено")

    except Exception as e:
        logger.exception(f"Ошибка отправки напоминания {reminder_id}: {e}")


# ============================================================
# JOB: ЕЖЕДНЕВНАЯ ПРОВЕРКА ИСТЕКАЮЩИХ PRO
# ============================================================
async def _check_expiring_pro_job() -> None:
    """Отправляет уведомления об истекающих PRO (за 1 день)."""
    from app.main import bot
    from app.database import db
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    from aiogram.exceptions import TelegramForbiddenError

    logger.info("Проверка истекающих PRO-подписок...")

    try:
        users = await db.fetch_all(
            """
            SELECT telegram_id, first_name, pro_expires_at
            FROM users
            WHERE tariff = 'pro'
              AND pro_expires_at IS NOT NULL
              AND pro_expires_at BETWEEN NOW() AND NOW() + INTERVAL '2 days'
            """
        )

        sent_count = 0
        for u in users:
            try:
                expires = u["pro_expires_at"]
                days_left = (expires - datetime.now(timezone.utc)).days

                if days_left > 1:
                    continue

                builder = InlineKeyboardBuilder()
                builder.row(InlineKeyboardButton(
                    text="💳 Продлить PRO",
                    callback_data="sub:show_pro",
                ))
                builder.row(InlineKeyboardButton(
                    text="🏠 В главное меню",
                    callback_data="menu:main",
                ))

                try:
                    await bot.send_message(
                        chat_id=u["telegram_id"],
                        text=(
                            f"⏰ <b>PRO заканчивается через 1 день</b>\n\n"
                            f"Дата окончания: <b>{expires.strftime('%d.%m.%Y')}</b>\n\n"
                            f"После окончания ты вернёшься на Free "
                            f"(3 задачи в месяц).\n\n"
                            f"Продли подписку, чтобы сохранить безлимит."
                        ),
                        reply_markup=builder.as_markup(),
                    )
                    sent_count += 1
                except TelegramForbiddenError:
                    logger.info(f"Пользователь {u['telegram_id']} заблокировал бота")
                    await db.execute(
                        "UPDATE users SET bot_blocked = TRUE WHERE telegram_id = %s",
                        (u["telegram_id"],),
                    )
                    continue

                logger.info(
                    f"Отправлено уведомление об окончании PRO "
                    f"user={u['telegram_id']}, {days_left} дн."
                )
            except Exception as e:
                logger.warning(
                    f"Не удалось уведомить {u['telegram_id']}: {e}"
                )

        logger.info(f"Проверка PRO завершена: отправлено {sent_count} уведомлений")

    except Exception as e:
        logger.exception(f"Ошибка в ежедневной проверке PRO: {e}")


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
scheduler_service = SchedulerService()