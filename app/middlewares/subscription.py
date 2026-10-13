"""
Middleware подписки.

Задачи:
1. Автопонижение PRO, если срок истёк.
2. Автоповышение до PRO для whitelist-пользователей.
3. Флаги is_pro, is_admin, is_whitelisted.
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
    """Проверяет и актуализирует статус подписки."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")

        if user is None:
            data["is_pro"] = False
            data["is_admin"] = False
            data["is_whitelisted"] = False
            return await handler(event, data)

        # --- Whitelist: автоповышение до PRO ---
        is_wl = False
        try:
            from app.services.whitelist import whitelist_service
            is_wl = await whitelist_service.is_whitelisted(user["telegram_id"])
        except Exception as e:
            logger.warning(f"Ошибка проверки whitelist: {e}")

        if is_wl and user["tariff"] != "pro":
            updated = await db.fetch_one(
                """
                UPDATE users
                SET tariff = 'pro', pro_expires_at = NULL
                WHERE id = %s
                RETURNING *
                """,
                (user["id"],),
            )
            if updated:
                user = updated
                data["user"] = updated
                logger.info(
                    f"Пользователь {user['telegram_id']} повышен до PRO (whitelist)"
                )

        # --- Автопонижение PRO, если истёк ---
        # (только если не whitelist)
        if not is_wl:
            user = await self._expire_pro_if_needed(user, data)

        # --- Флаги ---
        data["is_pro"] = user["tariff"] == "pro"
        data["is_whitelisted"] = is_wl
        data["is_admin"] = bool(
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
        """Понижает PRO → FREE, если срок истёк."""
        if user["tariff"] != "pro":
            return user

        expires_at = user.get("pro_expires_at")

        # PRO без срока — это whitelist, не трогаем
        if expires_at is None:
            return user

        now = datetime.now(timezone.utc)
        if expires_at <= now:
            logger.info(
                f"Пользователь {user['telegram_id']}: PRO истёк "
                f"{expires_at}. Понижаю до FREE."
            )
            return await self._downgrade_to_free(user, data)

        return user

    async def _downgrade_to_free(
        self,
        user: dict[str, Any],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Понижает до FREE."""
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
            return updated
        return user