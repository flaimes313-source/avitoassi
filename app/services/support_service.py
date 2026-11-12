"""
Сервис поддержки (тикеты).

Пользователь создаёт тикет → админ отвечает → пользователь видит ответ.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.database import db


class SupportService:
    """Управление тикетами и сообщениями."""

    # --------------------------------------------------------
    # СОЗДАНИЕ ТИКЕТА
    # --------------------------------------------------------
    async def create_ticket(
        self,
        user_id: int,
        subject: str,
        first_message: str,
    ) -> dict[str, Any]:
        """
        Создаёт тикет и добавляет первое сообщение от пользователя.
        """
        ticket = await db.execute_returning(
            """
            INSERT INTO support_tickets (
                user_id, subject, status, last_reply_by,
                unread_by_user, unread_by_admin
            )
            VALUES (%s, %s, 'open', 'user', 0, 1)
            RETURNING *
            """,
            (user_id, subject[:200]),
        )

        await db.execute(
            """
            INSERT INTO support_messages (ticket_id, sender, content)
            VALUES (%s, 'user', %s)
            """,
            (ticket["id"], first_message),
        )

        logger.info(
            f"Поддержка: создан тикет #{ticket['id']} "
            f"для user_id={user_id}"
        )

        # Уведомляем админа
        await self._notify_admin_new_ticket(ticket, first_message)

        return ticket

    # --------------------------------------------------------
    # СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ В ТИКЕТ
    # --------------------------------------------------------
    async def add_user_message(
        self,
        ticket_id: int,
        user_id: int,
        content: str,
    ) -> bool:
        """
        Добавляет сообщение пользователя в открытый тикет.
        Возвращает True, если успешно.
        """
        ticket = await db.fetch_one(
            """
            SELECT * FROM support_tickets
            WHERE id = %s AND user_id = %s
            """,
            (ticket_id, user_id),
        )
        if not ticket:
            return False

        if ticket["status"] == "closed":
            return False

        await db.execute(
            """
            INSERT INTO support_messages (ticket_id, sender, content)
            VALUES (%s, 'user', %s)
            """,
            (ticket_id, content),
        )

        await db.execute(
            """
            UPDATE support_tickets
            SET last_reply_by = 'user',
                unread_by_admin = unread_by_admin + 1,
                status = CASE WHEN status = 'in_progress' THEN 'open' ELSE status END,
                updated_at = NOW()
            WHERE id = %s
            """,
            (ticket_id,),
        )

        logger.info(f"Поддержка: сообщение пользователя в тикет #{ticket_id}")

        # Уведомляем админа
        await self._notify_admin_new_message(ticket, content)

        return True

    # --------------------------------------------------------
    # СООБЩЕНИЕ АДМИНА В ТИКЕТ
    # --------------------------------------------------------
    async def add_admin_message(
        self,
        ticket_id: int,
        admin_id: int,
        content: str,
    ) -> dict[str, Any] | None:
        """
        Добавляет сообщение админа. Уведомляет пользователя.
        Возвращает тикет или None.
        """
        ticket = await db.fetch_one(
            "SELECT * FROM support_tickets WHERE id = %s",
            (ticket_id,),
        )
        if not ticket:
            return None

        if ticket["status"] == "closed":
            return None

        await db.execute(
            """
            INSERT INTO support_messages (
                ticket_id, sender, admin_telegram_id, content
            )
            VALUES (%s, 'admin', %s, %s)
            """,
            (ticket_id, admin_id, content),
        )

        await db.execute(
            """
            UPDATE support_tickets
            SET last_reply_by = 'admin',
                unread_by_user = unread_by_user + 1,
                status = 'in_progress',
                updated_at = NOW()
            WHERE id = %s
            """,
            (ticket_id,),
        )

        logger.info(f"Поддержка: ответ админа в тикет #{ticket_id}")

        # Уведомляем пользователя
        await self._notify_user_new_reply(ticket, content)

        return ticket

    # --------------------------------------------------------
    # ЗАКРЫТИЕ ТИКЕТА
    # --------------------------------------------------------
    async def close_ticket(self, ticket_id: int) -> bool:
        """Закрывает тикет."""
        row = await db.execute_returning(
            """
            UPDATE support_tickets
            SET status = 'closed',
                closed_at = NOW(),
                updated_at = NOW()
            WHERE id = %s AND status <> 'closed'
            RETURNING *
            """,
            (ticket_id,),
        )
        if row:
            logger.info(f"Поддержка: тикет #{ticket_id} закрыт")
            return True
        return False

    # --------------------------------------------------------
    # СПИСКИ
    # --------------------------------------------------------
    async def get_user_tickets(
        self,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Возвращает тикеты пользователя (свежие сверху)."""
        return await db.fetch_all(
            """
            SELECT id, subject, status, last_reply_by,
                   unread_by_user, created_at, updated_at
            FROM support_tickets
            WHERE user_id = %s
            ORDER BY updated_at DESC
            LIMIT 10
            """,
            (user_id,),
        )

    async def get_open_tickets(self) -> list[dict[str, Any]]:
        """Возвращает открытые тикеты для админа."""
        return await db.fetch_all(
            """
            SELECT t.id, t.subject, t.status, t.last_reply_by,
                   t.unread_by_admin, t.created_at, t.updated_at,
                   u.telegram_id, u.username, u.first_name
            FROM support_tickets t
            JOIN users u ON u.id = t.user_id
            WHERE t.status <> 'closed'
            ORDER BY t.unread_by_admin DESC, t.updated_at DESC
            LIMIT 20
            """
        )

    async def get_ticket_with_messages(
        self,
        ticket_id: int,
    ) -> tuple[dict, list[dict]] | None:
        """Возвращает тикет + последние сообщения."""
        ticket = await db.fetch_one(
            """
            SELECT t.*, u.telegram_id, u.username, u.first_name
            FROM support_tickets t
            JOIN users u ON u.id = t.user_id
            WHERE t.id = %s
            """,
            (ticket_id,),
        )
        if not ticket:
            return None

        messages = await db.fetch_all(
            """
            SELECT id, sender, admin_telegram_id, content, created_at
            FROM support_messages
            WHERE ticket_id = %s
            ORDER BY created_at ASC
            LIMIT 50
            """,
            (ticket_id,),
        )

        return ticket, messages

    async def get_user_active_ticket(self, user_id: int) -> dict | None:
        """Возвращает последний открытый тикет пользователя (если есть)."""
        return await db.fetch_one(
            """
            SELECT * FROM support_tickets
            WHERE user_id = %s AND status <> 'closed'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        )

    # --------------------------------------------------------
    # ПРОЧТЕНИЕ
    # --------------------------------------------------------
    async def mark_read_by_user(self, ticket_id: int) -> None:
        await db.execute(
            "UPDATE support_tickets SET unread_by_user = 0 WHERE id = %s",
            (ticket_id,),
        )

    async def mark_read_by_admin(self, ticket_id: int) -> None:
        await db.execute(
            "UPDATE support_tickets SET unread_by_admin = 0 WHERE id = %s",
            (ticket_id,),
        )

    # --------------------------------------------------------
    # УВЕДОМЛЕНИЯ
    # --------------------------------------------------------
    async def _notify_admin_new_ticket(
        self,
        ticket: dict,
        message: str,
    ) -> None:
        """Уведомляет админа о новом тикете."""
        from app.main import bot
        from app.config import settings
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton

        try:
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(
                text="💬 Открыть тикет",
                callback_data=f"admin:ticket:{ticket['id']}",
            ))

            preview = message[:500] + ("..." if len(message) > 500 else "")

            await bot.send_message(
                chat_id=settings.admin_telegram_id,
                text=(
                    f"🎫 <b>Новый тикет #{ticket['id']}</b>\n\n"
                    f"📝 {ticket['subject']}\n\n"
                    f"{preview}"
                ),
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить админа о тикете: {e}")

    async def _notify_admin_new_message(
        self,
        ticket: dict,
        message: str,
    ) -> None:
        """Уведомляет админа о новом сообщении в тикете."""
        from app.main import bot
        from app.config import settings
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton

        try:
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(
                text="💬 Ответить",
                callback_data=f"admin:ticket:{ticket['id']}",
            ))

            preview = message[:300] + ("..." if len(message) > 300 else "")

            await bot.send_message(
                chat_id=settings.admin_telegram_id,
                text=(
                    f"💬 <b>Новое сообщение в тикете #{ticket['id']}</b>\n\n"
                    f"{preview}"
                ),
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить админа: {e}")

    async def _notify_user_new_reply(
        self,
        ticket: dict,
        message: str,
    ) -> None:
        """Уведомляет пользователя о новом ответе поддержки."""
        from app.main import bot
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton

        user = await db.fetch_one(
            "SELECT telegram_id FROM users WHERE id = %s",
            (ticket["user_id"],),
        )
        if not user:
            return

        try:
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(
                text="📬 Мои обращения",
                callback_data="support:list",
            ))

            await bot.send_message(
                chat_id=user["telegram_id"],
                text=(
                    f"💬 <b>Ответ поддержки</b>\n\n"
                    f"Тикет #{ticket['id']}: {ticket['subject']}\n\n"
                    f"{message}"
                ),
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя: {e}")


support_service = SupportService()