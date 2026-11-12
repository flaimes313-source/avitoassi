"""
Поддержка для пользователей.

Пользователь создаёт тикет → переписывается с админом в режиме чата.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app.database import db
from app.services.support_service import support_service
from app.utils.keyboards import (
    CB,
    main_menu_reply,
    support_menu,
)

router = Router(name="support")


class SupportStates(StatesGroup):
    waiting_subject = State()
    waiting_message = State()
    in_dialog = State()


# ============================================================
# МЕНЮ ПОДДЕРЖКИ
# ============================================================
@router.callback_query(F.data == CB.SET_SUPPORT)
async def show_support_menu(
    callback: CallbackQuery,
    user: dict,
) -> None:
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    await callback.message.edit_text(
        "💬 <b>Поддержка</b>\n\n"
        "Если что-то не работает или есть вопрос — напиши нам. "
        "Ответим в течение дня.\n\n"
        "Можно описать проблему в свободной форме.",
        reply_markup=support_menu(),
    )
    await callback.answer()


# ============================================================
# НАПИСАТЬ В ПОДДЕРЖКУ
# ============================================================
@router.callback_query(F.data == CB.SUPPORT_NEW)
async def start_new_ticket(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    # Проверяем, есть ли уже открытый тикет
    active = await support_service.get_user_active_ticket(user["id"])
    if active:
        await callback.answer(
            "У тебя уже есть открытое обращение",
            show_alert=True,
        )
        await state.update_data(ticket_id=active["id"])
        await state.set_state(SupportStates.in_dialog)
        await callback.message.answer(
            f"📬 У тебя открыт тикет <b>#{active['id']}</b>: {active['subject']}\n\n"
            f"Напиши сообщение — добавлю в этот тикет. "
            f"Или нажми «📬 Мои обращения», чтобы посмотреть историю.",
            reply_markup=main_menu_reply(),
        )
        return

    await state.set_state(SupportStates.waiting_message)
    await callback.message.answer(
        "✏️ <b>Напиши сообщение</b>\n\n"
        "Опиши, что случилось или что не работает. "
        "Чем подробнее — тем быстрее решим.\n\n"
        "Можно добавить скриншоты отдельными сообщениями.",
        reply_markup=None,
    )
    await callback.answer()


@router.message(SupportStates.waiting_message, F.text, ~F.text.startswith("/"))
async def on_first_message(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    if len(text) < 10:
        await message.answer(
            "🤔 Слишком коротко. Опиши подробнее, что случилось (минимум 10 символов)."
        )
        return

    # Создаём тикет
    ticket = await support_service.create_ticket(
        user_id=user["id"],
        subject=text[:80],
        first_message=text,
    )

    await state.update_data(ticket_id=ticket["id"])
    await state.set_state(SupportStates.in_dialog)

    await message.answer(
        f"✅ <b>Обращение #{ticket['id']} создано</b>\n\n"
        f"Мы ответим в течение дня — придёт уведомление.\n\n"
        f"Можешь писать сюда дополнительные сообщения — "
        f"они добавятся в этот же тикет.",
        reply_markup=main_menu_reply(),
    )
    logger.info(f"Поддержка: тикет #{ticket['id']} создан пользователем {user['telegram_id']}")


# ============================================================
# СООБЩЕНИЕ В ОТКРЫТОМ ТИКЕТЕ
# ============================================================
@router.message(SupportStates.in_dialog, F.text, ~F.text.startswith("/"))
async def on_dialog_message(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    if message.text in {
        "📝 Создать", "🛠 Улучшить", "🔍 Конкуренты", "📸 Фото",
        "📈 Стратегия", "💬 Ответы", "📂 Мои", "💳 Тариф", "⚙️ Настройки",
    }:
        return

    data = await state.get_data()
    ticket_id = data.get("ticket_id")

    if not ticket_id:
        await state.clear()
        await message.answer(
            "Ошибка: тикет потерян. Начни заново через 💬 Поддержка.",
            reply_markup=main_menu_reply(),
        )
        return

    ok = await support_service.add_user_message(
        ticket_id=ticket_id,
        user_id=user["id"],
        content=message.text,
    )

    if not ok:
        await state.clear()
        await message.answer(
            "⚠️ Тикет уже закрыт. Если нужна помощь — создай новое обращение.",
            reply_markup=main_menu_reply(),
        )
        return

    await message.answer(
        "✅ Сообщение добавлено в тикет. Мы ответим в течение дня.",
    )


# ============================================================
# МОИ ОБРАЩЕНИЯ
# ============================================================
@router.callback_query(F.data == CB.SUPPORT_LIST)
async def show_my_tickets(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    tickets = await support_service.get_user_tickets(user["id"])

    if not tickets:
        await callback.message.edit_text(
            "📬 <b>Мои обращения</b>\n\n"
            "Пока нет обращений.",
            reply_markup=support_menu(),
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    lines = [f"📬 <b>Мои обращения</b> ({len(tickets)})\n"]

    for t in tickets:
        status_emoji = {
            "open": "🟡",
            "in_progress": "🟢",
            "closed": "✅",
        }.get(t["status"], "❓")

        unread = " 🔴" if t["unread_by_user"] > 0 else ""

        lines.append(
            f"{status_emoji} <b>#{t['id']}</b>: {t['subject'][:60]}"
            f"{unread}"
        )

        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} #{t['id']} {t['subject'][:30]}",
            callback_data=f"support:view:{t['id']}",
        ))

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=CB.SET_SUPPORT))

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("support:view:"))
async def view_ticket(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    ticket_id = int(callback.data.split(":", 2)[2])

    result = await support_service.get_ticket_with_messages(ticket_id)
    if not result:
        await callback.answer("Тикет не найден.", show_alert=True)
        return

    ticket, messages = result

    # Проверяем, что это тикет этого пользователя
    owner = await db.fetch_one(
        "SELECT id FROM users WHERE id = %s AND id = (SELECT user_id FROM support_tickets WHERE id = %s)",
        (user["id"], ticket_id),
    )
    if not owner:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    # Помечаем прочитанным
    await support_service.mark_read_by_user(ticket_id)

    # Формируем текст
    status_label = {
        "open": "🟡 Открыт",
        "in_progress": "🟢 В работе",
        "closed": "✅ Закрыт",
    }.get(ticket["status"], ticket["status"])

    lines = [
        f"🎫 <b>Тикет #{ticket['id']}</b>\n",
        f"📝 {ticket['subject']}\n",
        f"Статус: {status_label}\n",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    for m in messages:
        time = m["created_at"].strftime("%d.%m %H:%M")
        if m["sender"] == "user":
            lines.append(f"👤 <b>Ты</b> <i>{time}</i>:\n{m['content']}")
        else:
            lines.append(f"🛠 <b>Поддержка</b> <i>{time}</i>:\n{m['content']}")
        lines.append("")

    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    if ticket["status"] != "closed":
        builder.row(InlineKeyboardButton(
            text="✏️ Ответить",
            callback_data=f"support:reply:{ticket_id}",
        ))

    builder.row(InlineKeyboardButton(text="🔙 К списку", callback_data=CB.SUPPORT_LIST))

    if len(text) > 4000:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for chunk in chunks[:-1]:
            await callback.message.answer(chunk)
        await callback.message.answer(chunks[-1], reply_markup=builder.as_markup())
    else:
        await callback.message.answer(text, reply_markup=builder.as_markup())

    await callback.answer()


@router.callback_query(F.data.startswith("support:reply:"))
async def reply_to_ticket(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    ticket_id = int(callback.data.split(":", 2)[2])

    await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportStates.in_dialog)

    await callback.message.answer(
        f"✏️ Напиши сообщение — добавлю в тикет #{ticket_id}.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer()