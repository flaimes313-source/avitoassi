"""
Сервис рассылок.

Админ создаёт рассылку → бот отправляет всем в выбранной аудитории.
Ограничение скорости: ~25 сообщений/сек (безопасный лимит Telegram).
Отслеживается bot_blocked — заблокировавшим не отправляем.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.database import db, to_jsonb


class BroadcastService:
    """Управление рассылками."""

    # Аудитории
    AUDIENCE_ALL = "all"
    AUDIENCE_ONBOARDED = "onboarded"
    AUDIENCE_PRO = "pro"
    AUDIENCE_FREE = "free"
    AUDIENCE_EX_PRO = "ex_pro"

    AUDIENCE_LABELS = {
        AUDIENCE_ALL: "Все пользователи",
        AUDIENCE_ONBOARDED: "Только активные (онбординг пройден)",
        AUDIENCE_PRO: "Только PRO",
        AUDIENCE_FREE: "Только Free",
        AUDIENCE_EX_PRO: "Бывшие PRO (истёк срок)",
    }

    # --------------------------------------------------------
    # ПОДСЧЁТ АУДИТОРИИ
    # --------------------------------------------------------
    async def count_audience(self, audience: str) -> int:
        """Считает количество получателей в аудитории."""
        query = self._audience_query(audience, count=True)
        result = await db.fetch_val(query)
        return int(result or 0)

    def _audience_query(self, audience: str, count: bool = False) -> str:
        """Формирует SQL по аудитории."""
        base = "FROM users WHERE bot_blocked = FALSE"

        if audience == self.AUDIENCE_ONBOARDED:
            base += " AND onboarded = TRUE"
        elif audience == self.AUDIENCE_PRO:
            base += " AND tariff = 'pro' AND pro_expires_at > NOW()"
        elif audience == self.AUDIENCE_FREE:
            base += " AND tariff = 'free'"
        elif audience == self.AUDIENCE_EX_PRO:
            base += " AND tariff = 'free' AND pro_expires_at IS NOT NULL"

        if count:
            return f"SELECT COUNT(*) {base}"
        return f"SELECT id, telegram_id {base}"

    # --------------------------------------------------------
    # СОЗДАНИЕ ЧЕРНОВИКА
    # --------------------------------------------------------
    async def create_broadcast(
        self,
        title: str,
        message_text: str,
        audience: str,
        media: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Создаёт черновик рассылки."""
        total = await self.count_audience(audience)

        row = await db.execute_returning(
            """
            INSERT INTO broadcasts (
                title, message_text, media, status,
                audience_filter, total_recipients,
                sent_count, failed_count
            )
            VALUES (%s, %s, %s::jsonb, 'draft', %s::jsonb, %s, 0, 0)
            RETURNING *
            """,
            (
                title[:200],
                message_text,
                to_jsonb(media or []),
                to_jsonb({"audience": audience}),
                total,
            ),
        )

        logger.info(
            f"Рассылка: создан черновик id={row['id']}, "
            f"аудитория={audience}, получателей={total}"
        )
        return row

    # --------------------------------------------------------
    # ЗАПУСК РАССЫЛКИ
    # --------------------------------------------------------
    async def send_broadcast(self, broadcast_id: int) -> dict[str, Any]:
        """
        Отправляет рассылку по аудитории.
        Возвращает итоговую статистику.
        """
        from app.main import bot
        from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

        broadcast = await db.fetch_one(
            "SELECT * FROM broadcasts WHERE id = %s",
            (broadcast_id,),
        )
        if not broadcast:
            raise ValueError(f"Рассылка {broadcast_id} не найдена")

        if broadcast["status"] == "running":
            raise ValueError("Рассылка уже запущена")

        if broadcast["status"] == "done":
            raise ValueError("Рассылка уже завершена")

        # Обновляем статус
        await db.execute(
            """
            UPDATE broadcasts
            SET status = 'running', started_at = NOW()
            WHERE id = %s
            """,
            (broadcast_id,),
        )

        # Получаем аудиторию
        audience = (broadcast.get("audience_filter") or {}).get("audience", self.AUDIENCE_ALL)
        query = self._audience_query(audience, count=False)
        recipients = await db.fetch_all(query)

        logger.info(
            f"Рассылка #{broadcast_id}: старт, "
            f"получателей={len(recipients)}, аудитория={audience}"
        )

        text = broadcast["message_text"]
        media = broadcast.get("media") or []
        photos = [
            m["file_id"] for m in media
            if m.get("type") == "photo" and m.get("file_id")
        ]

        sent = 0
        failed = 0

        for i, r in enumerate(recipients, start=1):
            telegram_id = r["telegram_id"]

            try:
                if photos:
                    await bot.send_photo(
                        chat_id=telegram_id,
                        photo=photos[0],
                        caption=text[:1024],
                    )
                    for extra_photo in photos[1:]:
                        await bot.send_photo(
                            chat_id=telegram_id,
                            photo=extra_photo,
                        )
                else:
                    await bot.send_message(
                        chat_id=telegram_id,
                        text=text,
                    )
                sent += 1

            except TelegramForbiddenError:
                # Пользователь заблокировал бота
                logger.info(
                    f"Рассылка #{broadcast_id}: {telegram_id} заблокировал бота"
                )
                await db.execute(
                    "UPDATE users SET bot_blocked = TRUE WHERE telegram_id = %s",
                    (telegram_id,),
                )
                failed += 1

            except TelegramRetryAfter as e:
                # Rate limit — ждём и повторяем
                wait = e.retry_after
                logger.warning(f"Rate limit, жду {wait} сек.")
                await asyncio.sleep(wait)
                # Повторная попытка
                try:
                    if photos:
                        await bot.send_photo(
                            chat_id=telegram_id,
                            photo=photos[0],
                            caption=text[:1024],
                        )
                    else:
                        await bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                        )
                    sent += 1
                except Exception as e2:
                    logger.warning(f"Повторная ошибка для {telegram_id}: {e2}")
                    failed += 1

            except Exception as e:
                logger.warning(
                    f"Рассылка #{broadcast_id}: ошибка для {telegram_id}: {e}"
                )
                failed += 1

            # Скорость: 20 сообщений/сек — безопасно
            if i % 20 == 0:
                await asyncio.sleep(1.0)

            # Обновляем прогресс каждые 50 отправленных
            if i % 50 == 0:
                await db.execute(
                    """
                    UPDATE broadcasts
                    SET sent_count = %s, failed_count = %s
                    WHERE id = %s
                    """,
                    (sent, failed, broadcast_id),
                )
                logger.info(
                    f"Рассылка #{broadcast_id}: прогресс {i}/{len(recipients)} "
                    f"(успешно: {sent}, ошибок: {failed})"
                )

        # Финал
        await db.execute(
            """
            UPDATE broadcasts
            SET status = 'done',
                sent_count = %s,
                failed_count = %s,
                finished_at = NOW()
            WHERE id = %s
            """,
            (sent, failed, broadcast_id),
        )

        logger.info(
            f"Рассылка #{broadcast_id}: завершена. "
            f"Успешно: {sent}, ошибок: {failed}, всего: {len(recipients)}"
        )

        return {
            "total": len(recipients),
            "sent": sent,
            "failed": failed,
        }

    # --------------------------------------------------------
    # ИСТОРИЯ РАССЫЛОК
    # --------------------------------------------------------
    async def get_recent_broadcasts(self, limit: int = 10) -> list[dict[str, Any]]:
        return await db.fetch_all(
            """
            SELECT id, title, status, audience_filter,
                   total_recipients, sent_count, failed_count,
                   created_at, started_at, finished_at
            FROM broadcasts
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )


broadcast_service = BroadcastService()