"""
Админ-панель.

Доступ: только для ADMIN_TELEGRAM_ID.
Функции: whitelist, PRO-пользователи, все пользователи,
поддержка (тикеты с фото), рассылки, статистика.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app.config import settings
from app.database import db
from app.services.whitelist import whitelist_service
from app.utils.keyboards import (
    CB,
    admin_panel,
    back_to_menu,
    broadcast_audience_menu,
    broadcast_confirm,
    broadcast_menu,
    main_menu_reply,
)

router = Router(name="admin")


class AdminStates(StatesGroup):
    waiting_add_id = State()
    waiting_add_note = State()
    waiting_remove_id = State()
    waiting_reply = State()


class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_audience = State()
    waiting_confirm = State()


def is_admin(user_id: int) -> bool:
    return user_id == settings.admin_telegram_id


# ============================================================
# /admin
# ============================================================
@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Команда доступна только администратору.")
        return

    await message.answer(
        "🔧 <b>Админ-панель</b>\n\nВыбери раздел:",
        reply_markup=admin_panel(),
    )


@router.callback_query(F.data == CB.ADMIN_PANEL)
async def show_admin_panel(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "🔧 <b>Админ-панель</b>\n\nВыбери раздел:",
        reply_markup=admin_panel(),
    )
    await callback.answer()


# ============================================================
# БЕЛЫЙ СПИСОК
# ============================================================
@router.callback_query(F.data == CB.ADMIN_WHITELIST)
async def show_whitelist(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    rows = await whitelist_service.list_all(only_active=True)

    if not rows:
        text = "📋 <b>Белый список пуст</b>"
    else:
        lines = [f"📋 <b>Белый список ({len(rows)}):</b>\n"]
        for r in rows:
            note = f" — <i>{r['note']}</i>" if r.get("note") else ""
            expires = ""
            if r.get("expires_at"):
                expires = f" (до {r['expires_at'].strftime('%d.%m.%Y')})"
            lines.append(f"• <code>{r['telegram_id']}</code>{note}{expires}")
        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить", callback_data="admin:wl:add"))
    builder.row(InlineKeyboardButton(text="➖ Удалить", callback_data="admin:wl:remove"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CB.ADMIN_PANEL))

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "admin:wl:add")
async def wl_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_add_id)
    await callback.message.edit_text(
        "➕ <b>Добавление в белый список</b>\n\n"
        "Пришли <b>Telegram ID</b> пользователя (числом).\n\n"
        "Как узнать ID: пусть пользователь напишет @userinfobot."
    )
    await callback.answer()


@router.message(AdminStates.waiting_add_id, F.text)
async def wl_add_id(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Нужно число. Попробуй ещё раз.")
        return

    telegram_id = int(text)
    await state.update_data(add_id=telegram_id)
    await state.set_state(AdminStates.waiting_add_note)

    await message.answer(
        f"✅ ID: <code>{telegram_id}</code>\n\n"
        f"Теперь напиши <b>заметку</b> (за что добавили).\n"
        f"Или напиши <code>-</code>, чтобы пропустить."
    )


@router.message(AdminStates.waiting_add_note, F.text)
async def wl_add_note(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    note = (message.text or "").strip()
    if note == "-":
        note = None

    data = await state.get_data()
    telegram_id = data.get("add_id")

    if not telegram_id:
        await message.answer("❌ Ошибка: ID потерян. Начни заново.")
        await state.clear()
        return

    await whitelist_service.add(
        telegram_id=telegram_id,
        added_by=message.from_user.id,
        note=note,
    )

    await state.clear()

    await message.answer(
        f"✅ <b>Добавлено в белый список</b>\n\n"
        f"ID: <code>{telegram_id}</code>\n"
        f"Заметка: {note or '—'}\n\n"
        f"Теперь этот пользователь получит безлимитный PRO.",
        reply_markup=admin_panel(),
    )
    logger.info(f"Админ {message.from_user.id} добавил {telegram_id} в whitelist")


@router.callback_query(F.data == "admin:wl:remove")
async def wl_remove_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_remove_id)
    await callback.message.edit_text(
        "➖ <b>Удаление из белого списка</b>\n\n"
        "Пришли <b>Telegram ID</b> для удаления."
    )
    await callback.answer()


@router.message(AdminStates.waiting_remove_id, F.text)
async def wl_remove_id(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Нужно число.")
        return

    telegram_id = int(text)
    removed = await whitelist_service.remove(telegram_id)
    await state.clear()

    if removed:
        await message.answer(
            f"✅ <code>{telegram_id}</code> удалён из белого списка.",
            reply_markup=admin_panel(),
        )
    else:
        await message.answer(
            f"⚠️ <code>{telegram_id}</code> не найден в белом списке.",
            reply_markup=admin_panel(),
        )


# ============================================================
# PRO-ПОЛЬЗОВАТЕЛИ
# ============================================================
@router.callback_query(F.data == CB.ADMIN_PRO_USERS)
async def show_pro_users(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    users = await db.fetch_all(
        """
        SELECT telegram_id, username, first_name, pro_expires_at
        FROM users
        WHERE tariff = 'pro'
          AND pro_expires_at IS NOT NULL
        ORDER BY pro_expires_at ASC
        """
    )

    if not users:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CB.ADMIN_PANEL))
        await callback.message.edit_text(
            "⭐ <b>PRO-пользователи</b>\n\nПока никого нет.",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    now = datetime.now(timezone.utc)
    lines = [f"⭐ <b>PRO-пользователи</b> ({len(users)})\n"]

    for u in users:
        expires = u["pro_expires_at"]
        days_left = (expires - now).days

        if days_left < 0:
            status = "❌ истёк"
        elif days_left == 0:
            status = "🟡 истекает сегодня"
        elif days_left <= 3:
            status = f"🟠 {days_left} дн."
        else:
            status = f"🟢 {days_left} дн."

        username = u.get("username")
        first_name = u.get("first_name") or "—"
        label = f"@{username}" if username else first_name

        lines.append(
            f"• <b>{label}</b> — <code>{u['telegram_id']}</code>\n"
            f"  {status} · до {expires.strftime('%d.%m.%Y')}"
        )

    expiring_soon = sum(
        1 for u in users
        if 0 <= (u["pro_expires_at"] - now).days <= 3
    )
    if expiring_soon:
        lines.append(f"\n⚠️ Истекает в ближайшие 3 дня: <b>{expiring_soon}</b>")

    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data=CB.ADMIN_PRO_USERS))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CB.ADMIN_PANEL))

    if len(text) > 4000:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for chunk in chunks[:-1]:
            await callback.message.answer(chunk)
        await callback.message.edit_text(
            chunks[-1],
            reply_markup=builder.as_markup(),
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
        )

    await callback.answer(f"PRO: {len(users)}")


# ============================================================
# ВСЕ ПОЛЬЗОВАТЕЛИ
# ============================================================
@router.callback_query(F.data == CB.ADMIN_ALL_USERS)
async def show_all_users(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    users = await db.fetch_all(
        """
        SELECT
            u.id,
            u.telegram_id,
            u.username,
            u.first_name,
            u.last_name,
            u.tariff,
            u.pro_expires_at,
            u.bot_blocked,
            u.onboarded,
            u.created_at,
            (SELECT COUNT(*) FROM items WHERE user_id = u.id) AS items_count,
            (SELECT COUNT(*) FROM tasks WHERE user_id = u.id) AS tasks_count,
            (SELECT MAX(created_at) FROM tasks WHERE user_id = u.id) AS last_activity
        FROM users u
        ORDER BY u.created_at DESC
        LIMIT 100
        """
    )

    if not users:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CB.ADMIN_PANEL))
        await callback.message.edit_text(
            "👥 <b>Все пользователи</b>\n\nПока никого нет.",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    total = len(users)
    pro_count = sum(1 for u in users if u["tariff"] == "pro")
    free_count = total - pro_count
    blocked_count = sum(1 for u in users if u["bot_blocked"])

    now = datetime.now(timezone.utc)
    lines = [
        f"👥 <b>Все пользователи</b> ({total})\n",
        f"📊 Статистика:",
        f"  • PRO: {pro_count}",
        f"  • Free: {free_count}",
        f"  • 🚫 Заблокировали бота: {blocked_count}\n",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    for u in users[:50]:
        username = u.get("username")
        first_name = u.get("first_name") or "—"
        label = f"@{username}" if username else first_name

        if u["tariff"] == "pro":
            expires = u.get("pro_expires_at")
            if expires:
                days = (expires - now).days
                if days < 0:
                    tariff_label = "⭐ PRO (истёк)"
                else:
                    tariff_label = f"⭐ PRO ({days} дн.)"
            else:
                tariff_label = "⭐ PRO"
        else:
            tariff_label = "🆓 Free"

        blocked = " 🚫" if u.get("bot_blocked") else ""
        onboarding = "" if u.get("onboarded") else " ⚠️не настроен"

        registered = u["created_at"].strftime("%d.%m.%Y")

        if u.get("last_activity"):
            activity = u["last_activity"].strftime("%d.%m")
        else:
            activity = "нет"

        stats = f"{u.get('items_count', 0)}📦 / {u.get('tasks_count', 0)}🎯"

        lines.append(
            f"<b>{label}</b>{blocked}{onboarding}\n"
            f"  🆔 <code>{u['telegram_id']}</code>\n"
            f"  {tariff_label} · Рег: {registered}\n"
            f"  Акт: {activity} · {stats}"
        )

    if total > 50:
        lines.append(f"\n<i>… и ещё {total - 50} пользователей</i>")

    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data=CB.ADMIN_ALL_USERS))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CB.ADMIN_PANEL))

    if len(text) > 4000:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for chunk in chunks[:-1]:
            await callback.message.answer(chunk)
        await callback.message.edit_text(
            chunks[-1],
            reply_markup=builder.as_markup(),
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
        )

    await callback.answer(f"Всего: {total}, PRO: {pro_count}, 🚫: {blocked_count}")


# ============================================================
# ТИКЕТЫ ПОДДЕРЖКИ — СПЕЦИФИЧНЫЕ ПЕРВЫМИ
# ============================================================

@router.callback_query(F.data.startswith("admin:ticket:reply:"))
async def reply_ticket_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Ошибка: неверный callback", show_alert=True)
        return

    try:
        ticket_id = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Ошибка: неверный ticket_id", show_alert=True)
        return

    await state.update_data(admin_ticket_id=ticket_id)
    await state.set_state(AdminStates.waiting_reply)

    await callback.message.answer(
        f"✏️ <b>Ответ на тикет #{ticket_id}</b>\n\n"
        f"Напиши текст или отправь скриншот с подписью.\n\n"
        f"Отменить: /cancel",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:ticket:close:"))
async def close_ticket(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Ошибка: неверный callback", show_alert=True)
        return

    try:
        ticket_id = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Ошибка: неверный ticket_id", show_alert=True)
        return

    from app.services.support_service import support_service

    ok = await support_service.close_ticket(ticket_id)

    if ok:
        await callback.answer("Тикет закрыт")
        await callback.message.edit_text(
            f"✅ Тикет #{ticket_id} закрыт.",
            reply_markup=admin_panel(),
        )
    else:
        await callback.answer("Не удалось закрыть", show_alert=True)


@router.callback_query(F.data.startswith("admin:ticket:"))
async def open_ticket(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка: неверный callback", show_alert=True)
        return

    if parts[2] in ("reply", "close"):
        return

    try:
        ticket_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка: неверный ticket_id", show_alert=True)
        return

    from app.services.support_service import support_service

    result = await support_service.get_ticket_with_messages(ticket_id)
    if not result:
        await callback.answer("Тикет не найден.", show_alert=True)
        return

    ticket, messages = result
    await support_service.mark_read_by_admin(ticket_id)

    status_label = {
        "open": "🟡 Открыт",
        "in_progress": "🟢 В работе",
        "closed": "✅ Закрыт",
    }.get(ticket["status"], ticket["status"])

    username = ticket.get("username")
    user_label = f"@{username}" if username else (ticket.get("first_name") or "—")

    header_text = (
        f"🎫 <b>Тикет #{ticket['id']}</b>\n"
        f"От: {user_label} (<code>{ticket['telegram_id']}</code>)\n"
        f"📝 {ticket['subject']}\n"
        f"Статус: {status_label}"
    )
    await callback.message.answer(header_text)

    for m in messages:
        time = m["created_at"].strftime("%d.%m %H:%M")
        sender = "👤 Пользователь" if m["sender"] == "user" else "🛠 Ты"
        content = m.get("content") or ""
        text = f"{sender} <i>{time}</i>:\n{content}" if content else f"{sender} <i>{time}</i>:"

        attachments = m.get("attachments") or []
        photos = [
            a["file_id"] for a in attachments
            if a.get("type") == "photo" and a.get("file_id")
        ]

        if photos:
            try:
                await callback.message.answer_photo(
                    photo=photos[0],
                    caption=text[:1024],
                )
                for extra in photos[1:]:
                    await callback.message.answer_photo(photo=extra)
            except Exception:
                await callback.message.answer(text)
        else:
            await callback.message.answer(text)

    builder = InlineKeyboardBuilder()
    if ticket["status"] != "closed":
        builder.row(InlineKeyboardButton(
            text="✏️ Ответить",
            callback_data=f"admin:ticket:reply:{ticket_id}",
        ))
        builder.row(InlineKeyboardButton(
            text="✅ Закрыть тикет",
            callback_data=f"admin:ticket:close:{ticket_id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 К тикетам", callback_data=CB.ADMIN_TICKETS))

    await callback.message.answer(
        "Действия:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == CB.ADMIN_TICKETS)
async def show_tickets(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    from app.services.support_service import support_service

    tickets = await support_service.get_open_tickets()

    if not tickets:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CB.ADMIN_PANEL))
        await callback.message.edit_text(
            "🎫 <b>Тикеты поддержки</b>\n\nОткрытых тикетов нет.",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    lines = [f"🎫 <b>Открытые тикеты</b> ({len(tickets)})\n"]

    for t in tickets:
        unread = f" 🔴{t['unread_by_admin']}" if t["unread_by_admin"] > 0 else ""
        status_emoji = "🟡" if t["status"] == "open" else "🟢"

        username = t.get("username")
        label = f"@{username}" if username else (t.get("first_name") or "—")

        lines.append(
            f"{status_emoji} <b>#{t['id']}</b> от {label}{unread}\n"
            f"  {t['subject'][:60]}"
        )

        btn_text = f"{status_emoji} #{t['id']}"
        if t["unread_by_admin"] > 0:
            btn_text += f" 🔴{t['unread_by_admin']}"
        btn_text += f" — {t['subject'][:25]}"

        builder.row(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"admin:ticket:{t['id']}",
        ))

    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data=CB.ADMIN_TICKETS))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CB.ADMIN_PANEL))

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
    )
    await callback.answer(f"Тикетов: {len(tickets)}")


@router.message(AdminStates.waiting_reply, F.text, ~F.text.startswith("/"))
async def send_ticket_reply_text(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    ticket_id = data.get("admin_ticket_id")

    if not ticket_id:
        await state.clear()
        await message.answer("Ошибка: тикет потерян.")
        return

    from app.services.support_service import support_service

    ok = await support_service.add_admin_message(
        ticket_id=ticket_id,
        admin_id=message.from_user.id,
        content=message.text,
    )

    await state.clear()

    if ok:
        await message.answer(
            f"✅ Ответ отправлен в тикет #{ticket_id}.",
            reply_markup=admin_panel(),
        )
    else:
        await message.answer(
            "⚠️ Не удалось отправить. Тикет закрыт или не найден.",
            reply_markup=admin_panel(),
        )


@router.message(AdminStates.waiting_reply, F.photo)
async def send_ticket_reply_photo(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    ticket_id = data.get("admin_ticket_id")

    if not ticket_id:
        await state.clear()
        await message.answer("Ошибка: тикет потерян.")
        return

    photo = message.photo[-1]
    caption = (message.caption or "").strip()

    from app.services.support_service import support_service

    ok = await support_service.add_admin_message(
        ticket_id=ticket_id,
        admin_id=message.from_user.id,
        content=caption,
        attachments=[{
            "type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
        }],
    )

    await state.clear()

    if ok:
        await message.answer(
            f"✅ Скриншот отправлен в тикет #{ticket_id}.",
            reply_markup=admin_panel(),
        )
    else:
        await message.answer(
            "⚠️ Не удалось отправить. Тикет закрыт или не найден.",
            reply_markup=admin_panel(),
        )


@router.message(Command("cancel"), AdminStates.waiting_reply)
async def cancel_admin_reply(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=admin_panel())


# ============================================================
# РАССЫЛКИ
# ============================================================
@router.callback_query(F.data == CB.ADMIN_BROADCAST)
async def show_broadcast_menu(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    from app.services.broadcast_service import broadcast_service

    recent = await broadcast_service.get_recent_broadcasts(limit=5)

    lines = ["📢 <b>Рассылки</b>\n"]

    if recent:
        lines.append("<b>Последние:</b>")
        for b in recent:
            status_emoji = {
                "draft": "📝",
                "running": "🔄",
                "done": "✅",
                "cancelled": "❌",
            }.get(b["status"], "❓")

            audience = (b.get("audience_filter") or {}).get("audience", "all")

            lines.append(
                f"{status_emoji} #{b['id']}: {b['title'][:40]}\n"
                f"   📤 {b['sent_count']}/{b['total_recipients']} · {audience}"
            )
    else:
        lines.append("Рассылок ещё не было.")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=broadcast_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == CB.BC_NEW)
async def broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(BroadcastStates.waiting_text)
    await state.update_data(bc_media=[])

    await callback.message.edit_text(
        "✉️ <b>Новая рассылка</b>\n\n"
        "Отправь текст сообщения (можно с фото — фото подписью к тексту).\n\n"
        "Форматирование: HTML поддерживается.\n\n"
        "Отменить: /cancel"
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_text, F.text, ~F.text.startswith("/"))
async def broadcast_text_received(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    text = (message.text or "").strip()
    if len(text) < 5:
        await message.answer("🤔 Слишком короткий текст. Минимум 5 символов.")
        return

    await state.update_data(bc_text=text)
    await state.set_state(BroadcastStates.waiting_audience)

    await message.answer(
        "✅ Текст сохранён.\n\nВыбери аудиторию:",
        reply_markup=broadcast_audience_menu(),
    )


@router.message(BroadcastStates.waiting_text, F.photo)
async def broadcast_photo_received(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    photo = message.photo[-1]
    caption = (message.caption or "").strip()

    data = await state.get_data()
    media = data.get("bc_media", [])

    if len(media) >= 10:
        await message.answer("⚠️ Максимум 10 фото.")
        return

    media.append({"type": "photo", "file_id": photo.file_id})

    await state.update_data(
        bc_media=media,
        bc_text=caption or data.get("bc_text", ""),
    )

    await message.answer(
        f"📸 Фото добавлено (всего: {len(media)}).\n\n"
        f"Отправь ещё фото или напиши текст."
    )


@router.callback_query(F.data.startswith("bc:audience:"))
async def broadcast_audience_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    audience = callback.data.split(":")[2]
    from app.services.broadcast_service import broadcast_service

    labels = broadcast_service.AUDIENCE_LABELS
    audience_label = labels.get(audience, audience)

    count = await broadcast_service.count_audience(audience)

    if count == 0:
        await callback.answer("В этой аудитории нет получателей", show_alert=True)
        return

    await state.update_data(bc_audience=audience)
    await state.set_state(BroadcastStates.waiting_confirm)

    data = await state.get_data()
    text = data.get("bc_text", "")
    media = data.get("bc_media", [])

    preview = text[:300] + ("..." if len(text) > 300 else "")

    await callback.message.edit_text(
        f"📢 <b>Проверь рассылку</b>\n\n"
        f"<b>Аудитория:</b> {audience_label}\n"
        f"<b>Получателей:</b> {count}\n"
        f"<b>Фото:</b> {len(media)}\n\n"
        f"<b>Текст:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{preview}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"Отправляем?",
        reply_markup=broadcast_confirm(audience_label, count),
    )
    await callback.answer()


@router.callback_query(F.data == CB.BC_SEND_NOW)
async def broadcast_send(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = await state.get_data()
    text = data.get("bc_text", "")
    media = data.get("bc_media", [])
    audience = data.get("bc_audience")

    if not text and not media:
        await callback.answer("Пустая рассылка", show_alert=True)
        return

    if not audience:
        await callback.answer("Аудитория не выбрана", show_alert=True)
        return

    from app.services.broadcast_service import broadcast_service

    labels = broadcast_service.AUDIENCE_LABELS
    audience_label = labels.get(audience, audience)

    title = text[:60] if text else "Рассылка с фото"
    broadcast = await broadcast_service.create_broadcast(
        title=title,
        message_text=text,
        audience=audience,
        media=media,
    )

    total = broadcast["total_recipients"]

    await callback.message.edit_text(
        f"🚀 <b>Рассылка #{broadcast['id']} запущена</b>\n\n"
        f"Аудитория: {audience_label}\n"
        f"Получателей: {total}\n\n"
        f"Отправляю… Это может занять несколько минут.\n"
        f"Пришлю отчёт, когда закончу."
    )
    await callback.answer("Запущено")

    await state.clear()

    try:
        result = await broadcast_service.send_broadcast(broadcast["id"])

        await callback.message.answer(
            f"✅ <b>Рассылка #{broadcast['id']} завершена</b>\n\n"
            f"📤 Отправлено: <b>{result['sent']}</b>\n"
            f"❌ Ошибок: {result['failed']}\n"
            f"👥 Всего: {result['total']}"
        )
    except Exception as e:
        logger.exception(f"Ошибка рассылки: {e}")
        await callback.message.answer(
            f"❌ Рассылка #{broadcast['id']} упала: {e}\n\n"
            f"Проверь статус в /admin → 📢 Рассылка.",
        )


@router.callback_query(F.data == CB.BC_HISTORY)
async def broadcast_history(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    from app.services.broadcast_service import broadcast_service

    broadcasts = await broadcast_service.get_recent_broadcasts(limit=10)

    if not broadcasts:
        await callback.message.edit_text(
            "📜 <b>История рассылок</b>\n\nРассылок не было.",
            reply_markup=broadcast_menu(),
        )
        await callback.answer()
        return

    lines = ["📜 <b>История рассылок</b>\n"]

    for b in broadcasts:
        status_emoji = {
            "draft": "📝",
            "running": "🔄",
            "done": "✅",
            "cancelled": "❌",
        }.get(b["status"], "❓")

        date = b["created_at"].strftime("%d.%m %H:%M")

        lines.append(
            f"{status_emoji} <b>#{b['id']}</b> от {date}\n"
            f"  {b['title'][:50]}\n"
            f"  📤 {b['sent_count']}/{b['total_recipients']} · ❌ {b['failed_count']}"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=broadcast_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == CB.BC_CANCEL)
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "❌ Рассылка отменена.",
        reply_markup=admin_panel(),
    )
    await callback.answer()


@router.message(Command("cancel"), BroadcastStates.waiting_text)
@router.message(Command("cancel"), BroadcastStates.waiting_audience)
@router.message(Command("cancel"), BroadcastStates.waiting_confirm)
async def cancel_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "❌ Рассылка отменена.",
        reply_markup=admin_panel(),
    )


# ============================================================
# СТАТИСТИКА
# ============================================================
@router.callback_query(F.data == CB.ADMIN_STATS)
async def admin_stats(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    total_users = await db.fetch_val("SELECT COUNT(*) FROM users")
    pro_users = await db.fetch_val("SELECT COUNT(*) FROM users WHERE tariff = 'pro'")
    wl_count = await db.fetch_val("SELECT COUNT(*) FROM whitelist WHERE is_active = TRUE")
    total_items = await db.fetch_val("SELECT COUNT(*) FROM items")
    total_tasks = await db.fetch_val("SELECT COUNT(*) FROM tasks")
    done_tasks = await db.fetch_val("SELECT COUNT(*) FROM tasks WHERE status = 'done'")

    tokens_today = await db.fetch_val(
        """
        SELECT COALESCE(SUM(total_tokens), 0) FROM gigachat_usage
        WHERE created_at >= CURRENT_DATE AND success = TRUE
        """
    ) or 0
    tokens_month = await db.fetch_val(
        """
        SELECT COALESCE(SUM(total_tokens), 0) FROM gigachat_usage
        WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE) AND success = TRUE
        """
    ) or 0
    calls_today = await db.fetch_val(
        "SELECT COUNT(*) FROM gigachat_usage WHERE created_at >= CURRENT_DATE"
    ) or 0
    calls_month = await db.fetch_val(
        "SELECT COUNT(*) FROM gigachat_usage WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)"
    ) or 0

    total_payments = await db.fetch_val(
        """
        SELECT COALESCE(SUM(amount), 0) FROM payments
        WHERE status = 'succeeded' AND activated_at IS NOT NULL
        """
    ) or 0

    open_tickets = await db.fetch_val(
        "SELECT COUNT(*) FROM support_tickets WHERE status <> 'closed'"
    ) or 0

    top_users = await db.fetch_all(
        """
        SELECT u.telegram_id, SUM(g.total_tokens) AS total
        FROM gigachat_usage g
        JOIN users u ON u.id = g.user_id
        WHERE g.created_at >= DATE_TRUNC('month', CURRENT_DATE)
          AND g.success = TRUE
        GROUP BY u.telegram_id
        ORDER BY total DESC
        LIMIT 3
        """
    )

    top_lines = []
    for row in top_users:
        top_lines.append(
            f"  • <code>{row['telegram_id']}</code>: {int(row['total']):,} токенов"
        )

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"⭐ PRO (платных): {pro_users}\n"
        f"🎁 Whitelist: {wl_count}\n"
        f"🎫 Тикетов открыто: {open_tickets}\n\n"
        f"📦 Товаров: {total_items}\n"
        f"🎯 Задач всего: {total_tasks}\n"
        f"✅ Успешных: {done_tasks}\n\n"
        f"💰 <b>Финансы</b>\n"
        f"Оплат PRO: {int(total_payments):,} ₽\n\n"
        f"🔢 <b>Расход GigaChat</b>\n"
        f"Сегодня: {int(tokens_today):,} токенов ({calls_today} вызовов)\n"
        f"За месяц: {int(tokens_month):,} токенов ({calls_month} вызовов)\n"
    )

    if top_lines:
        text += "\n🏆 <b>Топ-3 по расходу (месяц):</b>\n" + "\n".join(top_lines)

    await callback.message.edit_text(text, reply_markup=admin_panel())
    await callback.answer()