"""
Работа с белым списком пользователей.

Пользователи из whitelist получают безлимитный PRO без оплаты.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from app.database import db


class WhitelistService:
    """Управление белым списком."""

    async def is_whitelisted(self, telegram_id: int) -> bool:
        """
        Проверяет, в белом ли списке пользователь.
        Учитывает is_active и expires_at.
        """
        row = await db.fetch_one(
            """
            SELECT id, expires_at
            FROM whitelist
            WHERE telegram_id = %s AND is_active = TRUE
            LIMIT 1
            """,
            (telegram_id,),
        )
        if not row:
            return False

        # Проверяем срок, если задан
        expires_at = row.get("expires_at")
        if expires_at is not None:
            now = datetime.now(timezone.utc)
            if expires_at <= now:
                logger.info(
                    f"Whitelist: у {telegram_id} истёк срок ({expires_at})"
                )
                # Автоматически отключаем
                await db.execute(
                    "UPDATE whitelist SET is_active = FALSE WHERE id = %s",
                    (row["id"],),
                )
                return False

        return True

    async def add(
        self,
        telegram_id: int,
        added_by: int | None = None,
        note: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict:
        """
        Добавляет пользователя в белый список.
        Если уже есть — обновляет заметку и срок.
        """
        row = await db.execute_returning(
            """
            INSERT INTO whitelist (telegram_id, added_by, note, expires_at, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (telegram_id) DO UPDATE
                SET is_active = TRUE,
                    note = COALESCE(EXCLUDED.note, whitelist.note),
                    expires_at = EXCLUDED.expires_at,
                    added_by = COALESCE(EXCLUDED.added_by, whitelist.added_by)
            RETURNING *
            """,
            (telegram_id, added_by, note, expires_at),
        )
        logger.info(
            f"Whitelist: добавлен {telegram_id} "
            f"(by={added_by}, note={note!r})"
        )
        return row

    async def remove(self, telegram_id: int) -> bool:
        """Удаляет пользователя из белого списка. Возвращает True, если был."""
        row = await db.execute_returning(
            "DELETE FROM whitelist WHERE telegram_id = %s RETURNING id",
            (telegram_id,),
        )
        if row:
            logger.info(f"Whitelist: удалён {telegram_id}")
            return True
        return False

    async def list_all(self, only_active: bool = True) -> list[dict]:
        """Возвращает список всех записей."""
        query = "SELECT * FROM whitelist"
        if only_active:
            query += " WHERE is_active = TRUE"
        query += " ORDER BY created_at DESC"
        return await db.fetch_all(query)

    async def get(self, telegram_id: int) -> dict | None:
        """Возвращает запись по telegram_id."""
        return await db.fetch_one(
            "SELECT * FROM whitelist WHERE telegram_id = %s",
            (telegram_id,),
        )


whitelist_service = WhitelistService()