"""
Поддержка для пользователей.

Пользователь создаёт тикет → переписывается с админом в режиме чата.
Принимаются текстовые сообщения и скриншоты (photo).
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
        "Можно описать проблему текстом и приложить скриншоты.",
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
            f"Напиши сообщение — добавлю в этот тикет.",
            reply_markup=main_menu_reply(),
        )
        return

    await state.set_state(SupportStates.waiting_message)
    await state.update_data(
        pending_text="",
        pending_photos=[],
    )
    await callback.message.answer(
        "✏️ <b>Напиши сообщение</b>\n\n"
        "Опиши, что случилось. Можно приложить скриншоты — "
        "отправь их отдельными сообщениями, потом нажми /send.",
        reply_markup=None,
    )
    await callback.answer()


# ============================================================
# СБОР МАТЕРИАЛОВ (текст + фото)
# ============================================================
@router.message(SupportStates.waiting_message, F.text, ~F.text.startswith("/"))
async def on_first_text(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    data = await state.get_data()
    existing = data.get("pending_text", "")
    new_text = (existing + "\n\n" + text).strip() if existing else text

    await state.update_data(pending_text=new_text)

    photos = data.get("pending_photos", [])
    await message.answer(
        f"✅ Текст сохранён.\n\n"
        f"Можно добавить ещё текст или скриншоты. "
        f"Когда всё — нажми /send.",
    )


@router.message(SupportStates.waiting_message, F.photo)
async def on_first_photo(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    photo = message.photo[-1]

    data = await state.get_data()
    photos = data.get("pending_photos", [])

    if len(photos) >= 10:
        await message.answer("⚠️ Максимум 10 скриншотов.")
        return

    photos.append({
        "type": "photo",
        "file_id": photo.file_id,
        "file_unique_id": photo.file_unique_id,
    })

    await state.update_data(pending_photos=photos)
    await message.answer(
        f"📸 Скриншот добавлен (всего: {len(photos)}).\n\n"
        f"Когда всё — нажми /send.",
    )


@router.message(F.text == "/send", SupportStates.waiting_message)
async def send_first_ticket(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    data = await state.get_data()
    text = data.get("pending_text", "").strip()
    photos = data.get("pending_photos", [])

    if not text and not photos:
        await message.answer(
            "🤔 Пустой тикет. Напиши текст или пришли скриншот."
        )
        return

    subject = text[:80] if text else "Скриншот от пользователя"

    ticket = await support_service.create_ticket(
        user_id=user["id"],
        subject=subject,
        first_message=text,
        attachments=photos,
    )

    await state.update_data(ticket_id=ticket["id"])
    await state.set_state(SupportStates.in_dialog)

    await message.answer(
        f"✅ <b>Обращение #{ticket['id']} создано</b>\n\n"
        f"Мы ответим в течение дня — придёт уведомление.\n\n"
        f"Можешь писать сюда — сообщения добавятся в тикет.",
        reply_markup=main_menu_reply(),
    )
    logger.info(f"Поддержка: тикет #{ticket['id']} создан user={user['telegram_id']}")


# ============================================================
# СООБЩЕНИЕ В ОТКРЫТОМ ТИКЕТЕ
# ============================================================
@router.message(SupportStates.in_dialog, F.text, ~F.text.startswith("/"))
async def on_dialog_text(
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
            "⚠️ Тикет закрыт. Создай новое обращение через 💬 Поддержка.",
            reply_markup=main_menu_reply(),
        )
        return

    await message.answer("✅ Сообщение добавлено в тикет.")


@router.message(SupportStates.in_dialog, F.photo)
async def on_dialog_photo(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    """Фото в открытом тикете — добавляется как сообщение с attachment."""
    data = await state.get_data()
    ticket_id = data.get("ticket_id")

    if not ticket_id:
        return

    photo = message.photo[-1]
    caption = (message.caption or "").strip()

    ok = await support_service.add_user_message(
        ticket_id=ticket_id,
        user_id=user["id"],
        content=caption,
        attachments=[{
            "type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
        }],
    )

    if ok:
        await message.answer("📸 Скриншот добавлен в тикет.")
    else:
        await message.answer("⚠️ Тикет закрыт. Создай новое обращение.")


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
            "📬 <b>Мои обращения</b>\n\nПока нет обращений.",
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
            f"{status_emoji} <b>#{t['id']}</b>: {t['subject'][:60]}{unread}"
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
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка", show_alert=True)
        return

    try:
        ticket_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка", show_alert=True)
        return

    result = await support_service.get_ticket_with_messages(ticket_id)
    if not result:
        await callback.answer("Тикет не найден.", show_alert=True)
        return

    ticket, messages = result

    # Проверка владельца
    if ticket["user_id"] != user["id"]:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await support_service.mark_read_by_user(ticket_id)

    status_label = {
        "open": "🟡 Открыт",
        "in_progress": "🟢 В работе",
        "closed": "✅ Закрыт",
    }.get(ticket["status"], ticket["status"])

    # Заголовок
    await callback.message.answer(
        f"🎫 <b>Тикет #{ticket['id']}</b>\n"
        f"📝 {ticket['subject']}\n"
        f"Статус: {status_label}"
    )

    # Отправляем сообщения по одному (с фото)
    from aiogram.types import InputMediaPhoto

    for m in messages:
        time = m["created_at"].strftime("%d.%m %H:%M")
        sender = "👤 Ты" if m["sender"] == "user" else "🛠 Поддержка"
        text = f"{sender} <i>{time}</i>:\n{m['content']}" if m["content"] else f"{sender} <i>{time}</i>:"

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
            callback_data=f"support:reply:{ticket_id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 К списку", callback_data=CB.SUPPORT_LIST))

    await callback.message.answer(
        "Что дальше?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("support:reply:"))
async def reply_to_ticket(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка", show_alert=True)
        return

    try:
        ticket_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка", show_alert=True)
        return

    await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportStates.in_dialog)

    await callback.message.answer(
        f"✏️ Напиши сообщение — добавлю в тикет #{ticket_id}.\n"
        f"Можно приложить скриншот.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer()