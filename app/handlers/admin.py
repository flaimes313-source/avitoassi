"""
Админ-панель.

Доступ: только для ADMIN_TELEGRAM_ID.
Функции: белый список, статистика, тикеты (позже).
"""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
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


# ============================================================
# ФИЛЬТР: только админ
# ============================================================
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

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

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
        "Как узнать ID: пусть пользователь напишет @userinfobot — "
        "он покажет ID.",
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

    row = await whitelist_service.add(
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

    # Расход токенов
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
        """
        SELECT COUNT(*) FROM gigachat_usage
        WHERE created_at >= CURRENT_DATE
        """
    ) or 0
    calls_month = await db.fetch_val(
        """
        SELECT COUNT(*) FROM gigachat_usage
        WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)
        """
    ) or 0

    # Топ-3 пользователя по расходу за месяц
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
        f"🎁 Whitelist: {wl_count}\n\n"
        f"📦 Товаров: {total_items}\n"
        f"🎯 Задач всего: {total_tasks}\n"
        f"✅ Успешных: {done_tasks}\n\n"
        f"🔢 <b>Расход GigaChat</b>\n"
        f"Сегодня: {int(tokens_today):,} токенов ({calls_today} вызовов)\n"
        f"За месяц: {int(tokens_month):,} токенов ({calls_month} вызовов)\n"
    )

    if top_lines:
        text += "\n🏆 <b>Топ-3 по расходу (месяц):</b>\n" + "\n".join(top_lines)

    await callback.message.edit_text(text, reply_markup=admin_panel())
    await callback.answer()