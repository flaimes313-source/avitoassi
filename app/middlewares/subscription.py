"""
Middleware подписки.

Задачи:
1. Автоматически понижать PRO до FREE, если срок истёк.
2. Класть в data флаги: is_pro, is_admin.
3. Проверять лимиты перед запуском новой задачи.

ВАЖНО: сам middleware лимит НЕ списывает. Он только проверяет
и кладёт данные. Списание делает task_manager при создании задачи.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from loguru import logger

from app.config import settings
from app.database import db


class SubscriptionMiddleware(BaseMiddleware):
    """
    Проверяет и актуализирует статус подписки пользователя.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")

        # Пользователя ещё нет в БД — значит, /start ещё не выполнялся.
        # Просто пропускаем дальше, регистрация произойдёт в хендлере.
        if user is None:
            data["is_pro"] = False
            data["is_admin"] = False
            return await handler(event, data)

        # 1. Автоматическое истечение PRO
        user = await self._expire_pro_if_needed(user, data)

        # 2. Флаги
        data["is_pro"] = user["tariff"] == "pro"
        data["is_admin"] = (
            data.get("event_from_user")
            and data["event_from_user"].id == settings.admin_telegram_id
        )

        return await handler(event, data)

    # --------------------------------------------------------
    # ЛОГИКА ИСТЕЧЕНИЯ PRO
    # --------------------------------------------------------
    async def _expire_pro_if_needed(
        self,
        user: dict[str, Any],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Если срок PRO истёк — понижает до FREE и обновляет
        запись пользователя.
        """
        if user["tariff"] != "pro":
            return user

        expires_at = user.get("pro_expires_at")
        if expires_at is None:
            # Кривое состояние — PRO без срока. Понижаем.
            logger.warning(
                f"Пользователь {user['telegram_id']}: PRO без pro_expires_at. Понижаю до FREE."
            )
            return await self._downgrade_to_free(user, data)

        now = datetime.now(timezone.utc)
        if expires_at <= now:
            logger.info(
                f"Пользователь {user['telegram_id']}: PRO истёк {expires_at}. Понижаю до FREE."
            )
            return await self._downgrade_to_free(user, data)

        return user

    async def _downgrade_to_free(
        self,
        user: dict[str, Any],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Понижает пользователя до FREE и обновляет data["user"]."""
        updated = await db.fetch_one(
            """
            UPDATE users
            SET tariff = 'free',
                pro_expires_at = NULL
            WHERE id = %s
            RETURNING *
            """,
            (user["id"],),
        )
        if updated:
            data["user"] = updated
        return updated or user