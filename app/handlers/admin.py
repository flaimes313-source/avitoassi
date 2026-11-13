"""
Админ-панель.

Доступ: только для ADMIN_TELEGRAM_ID.
Функции: whitelist, PRO-пользователи, поддержка (тикеты с фото), статистика.
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
    main_menu_reply,
)

router = Router(name="admin")


class AdminStates(StatesGroup):
    waiting_add_id = State()
    waiting_add_note = State()
    waiting_remove_id = State()
    waiting_reply = State()


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
    builder.row(InlineKeyboardButton(
        text="🔄 Обновить", callback_data=CB.ADMIN_PRO_USERS,
    ))
    builder.row(InlineKeyboardButton(
        text="🔙 Назад", callback_data=CB.ADMIN_PANEL,
    ))

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
# ТИКЕТЫ ПОДДЕРЖКИ — СПЕЦИФИЧНЫЕ CALLBACKS ПЕРВЫМИ
# ============================================================

# --- 1. Ответ на тикет (самый специфичный) ---
@router.callback_query(F.data.startswith("admin:ticket:reply:"))
async def reply_ticket_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
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


# --- 2. Закрытие тикета ---
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


# --- 3. Открытие тикета (общий, ПОСЛЕ специфичных) ---
@router.callback_query(F.data.startswith("admin:ticket:"))
async def open_ticket(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
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

    # Заголовок
    header_text = (
        f"🎫 <b>Тикет #{ticket['id']}</b>\n"
        f"От: {user_label} (<code>{ticket['telegram_id']}</code>)\n"
        f"📝 {ticket['subject']}\n"
        f"Статус: {status_label}"
    )
    await callback.message.answer(header_text)

    # Сообщения по одному (с фото)
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

    # Кнопки
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


# --- 4. Список тикетов ---
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


# --- 5. Отправка ответа (текст) ---
@router.message(AdminStates.waiting_reply, F.text, ~F.text.startswith("/"))
async def send_ticket_reply_text(
    message: Message,
    state: FSMContext,
) -> None:
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


# --- 6. Отправка ответа (фото) ---
@router.message(AdminStates.waiting_reply, F.photo)
async def send_ticket_reply_photo(
    message: Message,
    state: FSMContext,
) -> None:
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
# СТАТИСТИКА
# ============================================================
@router.callback_query(F.data == CB.ADMIN_STATS)
async def admin_stats(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    total_users = await db.fetch_val("SELECT COUNT(*) FROM users")
    pro_users = await db.fetch_val("SELECT COUNT(*) FROM users WHERE tariff = 'pro'")
    wl_count = await db.fetch_val(
        "SELECT COUNT(*) FROM whitelist WHERE is_active = TRUE"
    )
    total_items = await db.fetch_val("SELECT COUNT(*) FROM items")
    total_tasks = await db.fetch_val("SELECT COUNT(*) FROM tasks")
    done_tasks = await db.fetch_val(
        "SELECT COUNT(*) FROM tasks WHERE status = 'done'"
    )

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
        """
        SELECT COUNT(*) FROM gigachat_usage
        WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)
        """
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
    # ============================================================
# ВСЕ ПОЛЬЗОВАТЕЛИ
# ============================================================
@router.callback_query(F.data == CB.ADMIN_ALL_USERS)
async def show_all_users(callback: CallbackQuery) -> None:
    """Список всех пользователей с деталями."""
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

    # Считаем статистику
    total = len(users)
    pro_count = sum(1 for u in users if u["tariff"] == "pro")
    free_count = total - pro_count
    blocked_count = sum(1 for u in users if u["bot_blocked"])

    # Формируем список
    now = datetime.now(timezone.utc)
    lines = [
        f"👥 <b>Все пользователи</b> ({total})\n",
        f"📊 Статистика:",
        f"  • PRO: {pro_count}",
        f"  • Free: {free_count}",
        f"  • 🚫 Заблокировали бота: {blocked_count}\n",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    for u in users[:50]:  # первые 50 для читаемости
        # Метка пользователя
        username = u.get("username")
        first_name = u.get("first_name") or "—"
        label = f"@{username}" if username else first_name

        # Тариф
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

        # Блокировка
        blocked = " 🚫" if u.get("bot_blocked") else ""

        # Онбординг
        onboarding = "" if u.get("onboarded") else " ⚠️не настроен"

        # Дата регистрации
        registered = u["created_at"].strftime("%d.%m.%Y")

        # Активность
        if u.get("last_activity"):
            activity = u["last_activity"].strftime("%d.%m")
        else:
            activity = "нет"

        # Статистика
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
    builder.row(InlineKeyboardButton(
        text="🔄 Обновить", callback_data=CB.ADMIN_ALL_USERS,
    ))
    builder.row(InlineKeyboardButton(
        text="🔙 Назад", callback_data=CB.ADMIN_PANEL,
    ))

    # Если длинно — разбиваем
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