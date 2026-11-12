"""
Сервис поддержки (тикеты).

Пользователь создаёт тикет → админ отвечает → пользователь видит ответ.
Поддерживаются текстовые сообщения и скриншоты (photo).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.database import db, to_jsonb


class SupportService:
    """Управление тикетами и сообщениями."""

    # --------------------------------------------------------
    # СОЗДАНИЕ ТИКЕТА
    # --------------------------------------------------------
    async def create_ticket(
        self,
        user_id: int,
        subject: str,
        first_message: str = "",
        attachments: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        Создаёт тикет и добавляет первое сообщение (текст и/или фото).
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
            INSERT INTO support_messages (
                ticket_id, sender, content, attachments
            )
            VALUES (%s, 'user', %s, %s::jsonb)
            """,
            (ticket["id"], first_message, to_jsonb(attachments or [])),
        )

        logger.info(
            f"Поддержка: создан тикет #{ticket['id']} "
            f"для user_id={user_id} (attachments: {len(attachments or [])})"
        )

        await self._notify_admin_new_ticket(
            ticket,
            first_message,
            attachments or [],
        )

        return ticket

    # --------------------------------------------------------
    # СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ
    # --------------------------------------------------------
    async def add_user_message(
        self,
        ticket_id: int,
        user_id: int,
        content: str = "",
        attachments: list[dict] | None = None,
    ) -> bool:
        """Добавляет сообщение пользователя в открытый тикет."""
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
            INSERT INTO support_messages (
                ticket_id, sender, content, attachments
            )
            VALUES (%s, 'user', %s, %s::jsonb)
            """,
            (ticket_id, content, to_jsonb(attachments or [])),
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

        logger.info(
            f"Поддержка: сообщение пользователя в тикет #{ticket_id} "
            f"(attachments: {len(attachments or [])})"
        )

        await self._notify_admin_new_message(
            ticket,
            content,
            attachments or [],
        )

        return True

    # --------------------------------------------------------
    # СООБЩЕНИЕ АДМИНА
    # --------------------------------------------------------
    async def add_admin_message(
        self,
        ticket_id: int,
        admin_id: int,
        content: str = "",
        attachments: list[dict] | None = None,
    ) -> dict[str, Any] | None:
        """Добавляет сообщение админа. Уведомляет пользователя."""
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
                ticket_id, sender, admin_telegram_id, content, attachments
            )
            VALUES (%s, 'admin', %s, %s, %s::jsonb)
            """,
            (ticket_id, admin_id, content, to_jsonb(attachments or [])),
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

        logger.info(
            f"Поддержка: ответ админа в тикет #{ticket_id} "
            f"(attachments: {len(attachments or [])})"
        )

        await self._notify_user_new_reply(
            ticket,
            content,
            attachments or [],
        )

        return ticket

    # --------------------------------------------------------
    # ЗАКРЫТИЕ
    # --------------------------------------------------------
    async def close_ticket(self, ticket_id: int) -> bool:
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
    async def get_user_tickets(self, user_id: int) -> list[dict[str, Any]]:
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
            SELECT id, sender, admin_telegram_id, content,
                   attachments, created_at
            FROM support_messages
            WHERE ticket_id = %s
            ORDER BY created_at ASC
            LIMIT 50
            """,
            (ticket_id,),
        )

        return ticket, messages

    async def get_user_active_ticket(self, user_id: int) -> dict | None:
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
        attachments: list[dict],
    ) -> None:
        from app.main import bot
        from app.config import settings
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton, InputMediaPhoto

        try:
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(
                text="💬 Открыть тикет",
                callback_data=f"admin:ticket:{ticket['id']}",
            ))

            # Формируем текст
            preview = message[:500] + ("..." if len(message) > 500 else "")
            attachments_note = ""
            if attachments:
                attachments_note = f"\n\n📎 Скриншотов: {len(attachments)}"

            text = (
                f"🎫 <b>Новый тикет #{ticket['id']}</b>\n\n"
                f"📝 {ticket['subject']}\n\n"
                f"{preview}{attachments_note}"
            )

            # Если есть фото — отправляем с фото
            photos = [
                a["file_id"] for a in attachments
                if a.get("type") == "photo" and a.get("file_id")
            ]

            if photos:
                # Отправляем первое фото с подписью, остальные — отдельно
                await bot.send_photo(
                    chat_id=settings.admin_telegram_id,
                    photo=photos[0],
                    caption=text[:1024],
                    reply_markup=builder.as_markup(),
                )
                for extra_photo in photos[1:]:
                    await bot.send_photo(
                        chat_id=settings.admin_telegram_id,
                        photo=extra_photo,
                    )
            else:
                await bot.send_message(
                    chat_id=settings.admin_telegram_id,
                    text=text,
                    reply_markup=builder.as_markup(),
                )
        except Exception as e:
            logger.warning(f"Не удалось уведомить админа о тикете: {e}")

    async def _notify_admin_new_message(
        self,
        ticket: dict,
        message: str,
        attachments: list[dict],
    ) -> None:
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
            attachments_note = f" 📎 {len(attachments)}" if attachments else ""

            text = (
                f"💬 <b>Новое сообщение в тикете #{ticket['id']}</b>{attachments_note}\n\n"
                f"{preview}"
            )

            photos = [
                a["file_id"] for a in attachments
                if a.get("type") == "photo" and a.get("file_id")
            ]

            if photos:
                await bot.send_photo(
                    chat_id=settings.admin_telegram_id,
                    photo=photos[0],
                    caption=text[:1024],
                    reply_markup=builder.as_markup(),
                )
                for extra_photo in photos[1:]:
                    await bot.send_photo(
                        chat_id=settings.admin_telegram_id,
                        photo=extra_photo,
                    )
            else:
                await bot.send_message(
                    chat_id=settings.admin_telegram_id,
                    text=text,
                    reply_markup=builder.as_markup(),
                )
        except Exception as e:
            logger.warning(f"Не удалось уведомить админа: {e}")

    async def _notify_user_new_reply(
        self,
        ticket: dict,
        message: str,
        attachments: list[dict],
    ) -> None:
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

            text = (
                f"💬 <b>Ответ поддержки</b>\n\n"
                f"Тикет #{ticket['id']}: {ticket['subject']}\n\n"
                f"{message}"
            )

            photos = [
                a["file_id"] for a in attachments
                if a.get("type") == "photo" and a.get("file_id")
            ]

            if photos:
                await bot.send_photo(
                    chat_id=user["telegram_id"],
                    photo=photos[0],
                    caption=text[:1024],
                    reply_markup=builder.as_markup(),
                )
                for extra_photo in photos[1:]:
                    await bot.send_photo(
                        chat_id=user["telegram_id"],
                        photo=extra_photo,
                    )
            else:
                await bot.send_message(
                    chat_id=user["telegram_id"],
                    text=text,
                    reply_markup=builder.as_markup(),
                )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя: {e}")


support_service = SupportService()