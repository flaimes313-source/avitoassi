"""
Тарифы и подписка (блоки 11–12 ТЗ).

Пользователь смотрит статус, оплачивает PRO через ЮKassa.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.config import settings
from app.database import db
from app.services.task_manager import task_manager
from app.services.yookassa_service import yookassa_service
from app.utils.keyboards import (
    CB,
    MENU,
    back_to_menu,
    main_menu_reply,
    subscription_menu,
    subscription_pro_offer,
)

router = Router(name="subscription")


# ============================================================
# МЕНЮ ТАРИФА
# ============================================================
@router.callback_query(F.data == CB.MENU_SUBSCRIPTION)
@router.message(F.text == MENU.SUBSCRIPTION)
async def show_subscription(
    event: Message | CallbackQuery,
    user: dict | None,
) -> None:
    logger.info(f"show_subscription: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    status = await task_manager.get_limit_status(user)

    tariff = user["tariff"]
    expires = user.get("pro_expires_at")
    is_pro = tariff == "pro"

    lines = ["💳 <b>Тариф и подписка</b>\n"]

    if is_pro:
        lines.append(f"⭐ <b>PRO активен</b>")
        if expires:
            days_left = (expires - datetime.now(timezone.utc)).days
            lines.append(f"Действует до: <b>{expires.strftime('%d.%m.%Y')}</b>")
            lines.append(f"<i>Осталось: {days_left} дн.</i>")
    else:
        lines.append(f"🆓 <b>Free</b>")

    lines.append(f"\n{status['text']}\n")

    lines.append("<b>Что даёт PRO:</b>")
    lines.append(f"• ⚡ До {settings.pro_daily_tasks} задач в день (вместо 3/мес)")
    lines.append("• 🔍 Анализ конкурентов")
    lines.append("• 📸 Расширенная помощь с фотографиями")
    lines.append("• 💬 Приоритетные ответы покупателям")
    lines.append("• 📈 Расширенные рекомендации")

    if not is_pro:
        lines.append(f"\n💰 Стоимость: <b>{settings.pro_price_rub} ₽ / 30 дней</b>")

    await message.answer(
        "\n".join(lines),
        reply_markup=subscription_menu(is_pro=is_pro),
    )


# ============================================================
# ОФФЕР PRO
# ============================================================
@router.callback_query(F.data == CB.SUB_SHOW_PRO)
async def show_pro_offer(
    callback: CallbackQuery,
    user: dict,
) -> None:
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    await callback.message.answer(
        f"⭐ <b>PRO на 30 дней</b>\n\n"
        f"<b>Что включено:</b>\n"
        f"• ⚡ До {settings.pro_daily_tasks} задач в день\n"
        f"• 🔍 Анализ конкурентов\n"
        f"• 📸 Расширенная помощь с фото\n"
        f"• 💬 Приоритетные ответы\n"
        f"• 📈 Расширенные рекомендации\n\n"
        f"<b>Стоимость:</b> {settings.pro_price_rub} ₽\n"
        f"<b>Срок:</b> 30 дней\n\n"
        f"Оплата через ЮKassa — безопасно.\n"
        f"Автосписания нет — подписка не продлится сама.",
        reply_markup=subscription_pro_offer(price=settings.pro_price_rub),
    )
    await callback.answer()


# ============================================================
# МОЙ ЛИМИТ / СТАТУС
# ============================================================
@router.callback_query(F.data == CB.SUB_MY_STATUS)
async def show_status(
    callback: CallbackQuery,
    user: dict,
) -> None:
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    status = await task_manager.get_limit_status(user)

    await callback.message.answer(
        f"📊 <b>Твой статус</b>\n\n{status['text']}",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


# ============================================================
# ОПЛАТА
# ============================================================
@router.callback_query(F.data == CB.SUB_PAY)
async def create_payment(
    callback: CallbackQuery,
    user: dict,
) -> None:
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    # Проверка: если PRO активен — может продлить?
    # Продление тоже возможно через оплату — активируется в конце
    await callback.answer("Создаю платёж…")
    await callback.message.answer("⏳ Создаю платёж в ЮKassa…")

    try:
        result = await yookassa_service.create_pro_payment(user)
    except Exception as e:
        logger.exception(f"Ошибка создания платежа: {e}")
        await callback.message.answer(
            "❌ Не удалось создать платёж. Попробуй позже или напиши в поддержку.",
            reply_markup=back_to_menu(),
        )
        return

    url = result["confirmation_url"]
    amount = result["amount"]

    # Кнопка с ссылкой на оплату
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"💳 Оплатить {amount:.0f} ₽",
        url=url,
    ))
    builder.row(InlineKeyboardButton(
        text="🔄 Проверить оплату",
        callback_data=f"sub:check:{result['payment_id']}",
    ))
    builder.row(InlineKeyboardButton(
        text="🏠 В главное меню",
        callback_data=CB.MENU_MAIN,
    ))

    await callback.message.answer(
        f"✅ <b>Платёж создан</b>\n\n"
        f"Сумма: {amount:.0f} ₽\n"
        f"PRO на 30 дней\n\n"
        f"Нажми «💳 Оплатить» ниже — откроется страница ЮKassa.\n\n"
        f"После оплаты вернись сюда и нажми «🔄 Проверить оплату».",
        reply_markup=builder.as_markup(),
    )


# ============================================================
# ПРОВЕРКА СТАТУСА ПЛАТЕЖА
# ============================================================
@router.callback_query(F.data.startswith("sub:check:"))
async def check_payment(
    callback: CallbackQuery,
    user: dict,
) -> None:
    payment_id = callback.data.split(":", 2)[2]
    logger.info(f"check_payment: {payment_id}")

    await callback.answer("Проверяю…")

    try:
        status_info = await yookassa_service.check_payment_status(payment_id)
    except Exception as e:
        logger.exception(f"Ошибка проверки: {e}")
        await callback.message.answer(
            "❌ Не удалось проверить платёж. Попробуй позже.",
            reply_markup=back_to_menu(),
        )
        return

    real_status = status_info["status"]

    if real_status == "succeeded":
        # Активируем (или уже активирован через webhook)
        payment_row = await db.fetch_one(
            "SELECT * FROM payments WHERE yookassa_payment_id = %s",
            (payment_id,),
        )

        if payment_row and not payment_row.get("activated_at"):
            # Webhook не сработал — активируем вручную
            await yookassa_service._activate_pro(payment_row)
            await callback.message.answer(
                "🎉 <b>Оплата подтверждена!</b>\n\nPRO активирован на 30 дней.",
                reply_markup=main_menu_reply(),
            )
        else:
            await callback.message.answer(
                "✅ <b>Оплата уже зачислена</b>\n\nPRO активен.",
                reply_markup=main_menu_reply(),
            )
        return

    if real_status == "canceled":
        await callback.message.answer(
            "❌ <b>Платёж отменён</b>\n\n"
            "Деньги не списаны. Можно попробовать снова.",
            reply_markup=subscription_pro_offer(price=settings.pro_price_rub),
        )
        return

    # pending / waiting_for_capture
    await callback.message.answer(
        f"⏳ <b>Платёж ещё не завершён</b>\n\n"
        f"Статус: {real_status}\n\n"
        f"Если ты уже оплатил — подожди пару минут и проверь снова.",
        reply_markup=back_to_menu(),
    )


# ============================================================
# ПРОДЛЕНИЕ
# ============================================================
@router.callback_query(F.data == CB.SUB_EXTEND)
async def extend_pro(
    callback: CallbackQuery,
    user: dict,
) -> None:
    """Продление PRO — тот же оффер, что и первая оплата."""
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    expires = user.get("pro_expires_at")
    text = (
        f"🔄 <b>Продление PRO</b>\n\n"
        f"Текущий PRO действует до: "
        f"<b>{expires.strftime('%d.%m.%Y')}</b>\n\n"
        f"При оплате +30 дней добавятся к текущему сроку.\n\n"
        f"<b>Стоимость:</b> {settings.pro_price_rub} ₽"
    ) if expires else (
        f"🔄 <b>Продление PRO</b>\n\n"
        f"Оплата на 30 дней вперёд.\n\n"
        f"<b>Стоимость:</b> {settings.pro_price_rub} ₽"
    )

    await callback.message.answer(
        text,
        reply_markup=subscription_pro_offer(price=settings.pro_price_rub),
    )
    await callback.answer()