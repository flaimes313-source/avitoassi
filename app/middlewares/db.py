"""
Middleware базы данных.

Кладёт в data["db"] глобальный пул соединений и
в data["user"] — запись пользователя из БД (если есть).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from loguru import logger

from app.database import db


class DbSessionMiddleware(BaseMiddleware):
    """
    Инжектит db и user в контекст обработки события.

    Используется в хендлерах так:
        async def handler(message: Message, db, user):
            # db   — объект Database
            # user — dict с данными пользователя или None
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # 1. Кладём пул соединений
        data["db"] = db

        # 2. Пытаемся найти пользователя в БД
        tg_user: TgUser | None = data.get("event_from_user")

        logger.info(
            f"DbSessionMiddleware: event={type(event).__name__}, "
            f"tg_user={tg_user.id if tg_user else None}"
        )

        if tg_user is not None:
            try:
                user_row = await db.fetch_one(
                    "SELECT * FROM users WHERE telegram_id = %s",
                    (tg_user.id,),
                )
                data["user"] = user_row
                logger.info(
                    f"   user найден: {user_row is not None}"
                    + (f", tariff={user_row['tariff']}" if user_row else "")
                )
            except Exception as e:
                logger.exception(f"Ошибка загрузки пользователя {tg_user.id}: {e}")
                data["user"] = None
        else:
            data["user"] = None
            logger.info("   event_from_user отсутствует, user=None")

        return await handler(event, data)